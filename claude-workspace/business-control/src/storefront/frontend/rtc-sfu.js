/* The SFU transport — for classes too big for a peer-to-peer mesh.
 * Ported from lingua-portal's lib/sfu.js.
 *
 * WHY A SECOND TRANSPORT. In the mesh every participant uploads their
 * camera to every other one, so upload cost grows with the class: six is
 * fine, thirty is not — that is 29 outbound streams from a teacher's
 * laptop. An SFU (Selective Forwarding Unit) fixes exactly that: you
 * upload ONCE to the server, and it forwards your stream to everyone
 * else. Upload becomes constant instead of linear.
 *
 * WHY WHIP/WHEP. Every SFU vendor ships a JavaScript SDK, and using one
 * would marry this app to one vendor and add its first such dependency.
 * WHIP (RFC 9725) and WHEP do the same job over plain HTTP: POST an SDP
 * offer, get an SDP answer, DELETE to hang up. Works with Cloudflare
 * Realtime, MediaMTX, Janus, LiveKit ingress — swapping vendors becomes a
 * config change (whip_url / whep_url / sfu_token on the install).
 *
 * WHAT THE PLATFORM STILL PROVIDES. WHIP/WHEP describe publishing and
 * subscribing to ONE stream each; they say nothing about who is in a
 * room. The existing signaling mailboxes (/api/learn/rtc/...) keep
 * answering that, and everyone subscribes to everyone else's published
 * stream — one WHEP connection per remote participant, download-only.
 *
 * The exported interface is IDENTICAL to createMesh, which is what makes
 * the choice a config switch rather than a rewrite: the caller picks a
 * factory and never learns which.
 */
(function () {
  "use strict";

  const POLL_MS = 1000;

  // Wait for ICE gathering before POSTing: WHIP is one request/response —
  // there is no channel to trickle later candidates over. The timeout
  // means a stalled STUN server delays a class rather than cancelling it.
  function iceComplete(pc, timeoutMs = 4000) {
    if (pc.iceGatheringState === "complete") return Promise.resolve();
    return new Promise((resolve) => {
      const done = () => {
        pc.removeEventListener("icegatheringstatechange", check);
        resolve();
      };
      const check = () => {
        if (pc.iceGatheringState === "complete") done();
      };
      pc.addEventListener("icegatheringstatechange", check);
      setTimeout(done, timeoutMs);
    });
  }

  async function sdpExchange(url, offerSdp, opts) {
    const { token = "" } = opts || {};
    const headers = { "Content-Type": "application/sdp" };
    if (token) headers["Authorization"] = "Bearer " + token;
    const res = await fetch(url, { method: "POST", headers, body: offerSdp });
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      throw new Error(`the media server refused the connection (${res.status})${
        detail ? ": " + detail.slice(0, 120) : ""}`);
    }
    const answer = await res.text();
    // 201 Created carries the resource URL used to hang up. Relative
    // Locations are legal, so resolve against the request URL.
    const loc = res.headers.get("Location");
    const resource = loc ? new URL(loc, url).toString() : "";
    return { answer, resource };
  }

  // Ordered high-to-low: that is the order the RID list must appear in and
  // the order every SFU assumes. Bitrates are ceilings, not targets.
  const LAYERS = [
    { rid: "h", maxBitrate: 900000, scaleResolutionDownBy: 1 },
    { rid: "m", maxBitrate: 300000, scaleResolutionDownBy: 2 },
    { rid: "l", maxBitrate: 100000, scaleResolutionDownBy: 4 },
  ];

  // Which simulcast layers to publish. Pure, so the policy is testable
  // without a browser, an SFU, or a camera. A single encoding means "no
  // simulcast" — one layer is exactly what plain addTrack does.
  function simulcastEncodings(cfg) {
    cfg = cfg || {};
    if (cfg.simulcast === false) return [{ ...LAYERS[0] }];
    // Each layer is a separate encode of the same frame: on a 2-core
    // machine three encodes is a hot device and a stuttering class, so
    // the middle layer goes and the useful extremes stay.
    const cores = Number(cfg.hardware_concurrency || 0);
    let layers = cores && cores <= 2 ? [LAYERS[0], LAYERS[2]] : LAYERS.slice();
    const max = Number(cfg.max_layers || 0);
    if (max > 0) layers = layers.slice(0, max);
    const up = Number(cfg.uplink_kbps || 0);
    if (up > 0) {
      const affordable = layers.filter((l) => l.maxBitrate / 1000 <= up * 0.8);
      layers = affordable.length ? affordable : [LAYERS[LAYERS.length - 1]];
    }
    return layers.map((l) => ({ ...l }));
  }

  function createSfu({ room, api, config, onLocal, onRemote, onLeave,
                       onState, onError, onMedia }) {
    const cfg = config || {};
    const ice = cfg.ice_servers && cfg.ice_servers.length
      ? cfg.ice_servers : [{ urls: ["stun:stun.l.google.com:19302"] }];
    const base = "/api/learn/rtc/" + encodeURIComponent(room);

    let local = null;
    let selfId = null;
    let publishPc = null;
    let publishResource = "";
    const subs = new Map();        // peerId -> { pc, resource }
    let poller = null;
    let stopped = false;

    const say = (m) => { try { onState && onState(m); } catch (e) {} };
    const oops = (e) => {
      try { onError && onError(String((e && e.message) || e)); } catch (x) {}
    };
    const url = (tpl, id) => String(tpl || "")
      .replace("{room}", encodeURIComponent(room))
      .replace("{id}", encodeURIComponent(id));

    async function publish() {
      // Watching only: a WHIP offer with no tracks is not a thing an SFU
      // can act on, so skip the publish entirely.
      if (!local || !local.getTracks().length) { say("watching only"); return; }
      publishPc = new RTCPeerConnection({ iceServers: ice });
      // Simulcast: the camera at three sizes at once, and the SFU forwards
      // whichever each viewer can use — the phone on hotel wifi gets the
      // quarter-size layer without dragging the whole class down to it.
      // sendEncodings MUST be set at construction: setParameters can shrink
      // or disable a layer but can never create one.
      const encodings = simulcastEncodings(cfg);
      for (const track of local.getTracks()) {
        if (track.kind === "video" && encodings.length > 1) {
          publishPc.addTransceiver(track, { direction: "sendonly",
            streams: [local], sendEncodings: encodings });
        } else {
          publishPc.addTrack(track, local);
        }
      }
      const offer = await publishPc.createOffer();
      await publishPc.setLocalDescription(offer);
      await iceComplete(publishPc);
      const { answer, resource } = await sdpExchange(
        url(cfg.whip_url, selfId), publishPc.localDescription.sdp,
        { token: cfg.token });
      await publishPc.setRemoteDescription({ type: "answer", sdp: answer });
      publishResource = resource;
      say("publishing");
    }

    async function subscribe(peerId) {
      if (subs.has(peerId) || peerId === selfId) return;
      const pc = new RTCPeerConnection({ iceServers: ice });
      subs.set(peerId, { pc, resource: "" });
      // Download-only, declared up front, so the SFU allocates no inbound
      // slot for this connection.
      pc.addTransceiver("video", { direction: "recvonly" });
      pc.addTransceiver("audio", { direction: "recvonly" });
      pc.ontrack = (e) => {
        const stream = (e.streams && e.streams[0])
          || new MediaStream([e.track]);
        onRemote && onRemote(peerId, stream);
      };
      pc.onconnectionstatechange = () => {
        if (["failed", "closed"].includes(pc.connectionState)) drop(peerId);
      };
      try {
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        await iceComplete(pc);
        const { answer, resource } = await sdpExchange(
          url(cfg.whep_url, peerId), pc.localDescription.sdp,
          { token: cfg.token });
        await pc.setRemoteDescription({ type: "answer", sdp: answer });
        subs.set(peerId, { pc, resource });
      } catch (e) {
        // One participant we cannot subscribe to must not take down the
        // whole class.
        drop(peerId);
        oops(e);
      }
    }

    function drop(peerId) {
      const s = subs.get(peerId);
      if (!s) return;
      try { s.pc.close(); } catch (e) {}
      if (s.resource) fetch(s.resource, { method: "DELETE" }).catch(() => {});
      subs.delete(peerId);
      onLeave && onLeave(peerId);
    }

    async function poll() {
      if (stopped) return;
      try {
        const r = await api(base + "/poll?peer=" + encodeURIComponent(selfId));
        const present = new Set(r.peers || []);
        for (const id of [...subs.keys()]) if (!present.has(id)) drop(id);
        for (const id of present) if (!subs.has(id)) subscribe(id);
      } catch (e) { /* transient — keep polling */ }
      if (!stopped) poller = setTimeout(poll, POLL_MS);
    }

    return {
      async join() {
        stopped = false;
        if (!cfg.whip_url || !cfg.whep_url) {
          throw new Error("the media server is not configured here");
        }
        const got = await window.LinguaMesh.acquireMedia();
        local = got.stream;
        if (local) onLocal && onLocal(local);
        if (got.level !== "full" && onMedia) onMedia(got);
        const r = await api(base + "/join", {});
        selfId = r.peer;
        await publish();
        for (const id of r.peers || []) subscribe(id);
        poll();
        return { selfId, peers: r.peers || [] };
      },

      leave() {
        stopped = true;
        if (poller) clearTimeout(poller);
        for (const id of [...subs.keys()]) drop(id);
        if (publishPc) { try { publishPc.close(); } catch (e) {} publishPc = null; }
        if (publishResource) {
          fetch(publishResource, { method: "DELETE" }).catch(() => {});
          publishResource = "";
        }
        if (local) { for (const t of local.getTracks()) t.stop(); local = null; }
        if (selfId) api(base + "/leave", { peer: selfId }).catch(() => {});
        selfId = null;
        say("left");
      },

      has(kind) {
        if (!local) return false;
        return (kind === "video" ? local.getVideoTracks()
                                 : local.getAudioTracks()).length > 0;
      },

      // The interface matches the mesh's, the mechanism differs: WHIP
      // published a fixed offer, so adding a camera means tearing the old
      // publication down and republishing, not renegotiating in place.
      async addCamera() {
        const got = await window.LinguaMesh.acquireMedia();
        if (!got.stream || !got.stream.getVideoTracks().length) {
          throw new Error(got.detail || "no camera is available");
        }
        const track = got.stream.getVideoTracks()[0];
        if (!local) local = got.stream;
        else local.addTrack(track);
        onLocal && onLocal(local);
        if (publishPc) {
          try {
            if (publishResource) {
              await fetch(publishResource, { method: "DELETE" });
            }
          } catch (e) {}
          try { publishPc.close(); } catch (e) {}
          publishPc = null;
          publishResource = "";
        }
        await publish();
        return true;
      },

      toggle(kind) {
        if (!local) return false;
        const tracks = kind === "video" ? local.getVideoTracks()
                                        : local.getAudioTracks();
        if (!tracks.length) return false;
        const on = !tracks[0].enabled;
        for (const t of tracks) t.enabled = on;
        return on;
      },
      enabled(kind) {
        if (!local) return false;
        const t = (kind === "video" ? local.getVideoTracks()
                                    : local.getAudioTracks())[0];
        return !!(t && t.enabled);
      },
      get id() { return selfId; },
      get peerIds() { return [...subs.keys()]; },
    };
  }

  // Which transport a room should use. Pure and stated once. "auto" stays
  // on the mesh — no server hop, no media touching infrastructure — until
  // the class outgrows it AND an SFU is actually configured.
  function chooseTransport(config, participantCount) {
    const cfg = config || {};
    if (cfg.mode === "sfu") return "sfu";
    if (cfg.mode === "mesh") return "mesh";
    if (cfg.available && participantCount >= (cfg.mesh_max || 12)) return "sfu";
    return "mesh";
  }

  function capacityNote(transport, config, participantCount) {
    const max = (config && config.mesh_max) || 12;
    if (transport === "sfu") {
      return "via the media server — suitable for a full class";
    }
    if (participantCount >= max) {
      return (config && config.available)
        ? "switching to the media server as the class grows"
        : `peer-to-peer with ${participantCount} in the call, past the`
          + ` comfortable limit of ${max} — configure a media server for`
          + " classes this size";
    }
    return `peer-to-peer, works well up to about ${max}`;
  }

  window.LinguaSfu = { createSfu, chooseTransport, capacityNote,
                       simulcastEncodings, LAYERS };
})();
