/* A peer-to-peer WebRTC mesh for the live class. Ported from lingua-portal.
 *
 * The server never touches media: it only relays SDP and ICE between
 * browsers (/api/learn/rtc/*). Each participant holds one RTCPeerConnection
 * per OTHER participant — a full mesh: the right shape for a language class
 * of a handful of people, the wrong shape for thirty (an SFU slots in behind
 * this same interface when that day comes).
 *
 * Deliberately IMPERATIVE and outside any view framework: RTCPeerConnection
 * is a stateful machine that must survive re-renders. The app talks through
 * a small command surface (join/leave/toggle) and receives callbacks.
 *
 * Negotiation is the "perfect negotiation" pattern: two peers can offer
 * simultaneously (glare); each pair agrees deterministically who is POLITE —
 * by comparing peer ids — and the polite one rolls back its own offer when
 * it collides. The only approach that neither deadlocks nor livelocks under
 * real network timing.
 *
 * Exposed as window.LinguaMesh — used by the storefront's /learn page and by
 * the ops roster screen: one client, not two.
 */
(function () {
  "use strict";

  /* ── media: getting a camera and microphone, and coping without one ──────
   * getUserMedia({video, audio}) fails as a unit, and treating that as a
   * failure to join is wrong in the most ordinary case there is: a desktop
   * with no webcam. So this degrades — both, then each device ALONE (one
   * busy microphone must not cost you a working camera), then nothing at
   * all: watch and listen; you are in the room, just not on screen. The
   * distinction that matters most is DENIED versus ABSENT — a permission
   * the person can grant versus hardware they do not have. */

  const EXPLAIN = {
    denied: "this browser is blocking the camera and microphone — allow them in the address bar",
    absent: "no camera or microphone was found on this device",
    busy: "the camera or microphone is already in use by another app",
    failed: "the camera and microphone could not be started",
  };

  function classify(err) {
    const name = (err && err.name) || "";
    if (name === "NotAllowedError" || name === "SecurityError") return "denied";
    if (name === "NotFoundError" || name === "OverconstrainedError") return "absent";
    if (name === "NotReadableError" || name === "AbortError") return "busy";
    return "failed";
  }

  async function acquireMedia() {
    if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) {
      return { stream: null, level: "none", reason: "insecure",
               detail: "camera and microphone need https or localhost" };
    }
    const tryGet = async (c) => {
      try { return { stream: await navigator.mediaDevices.getUserMedia(c), why: "" }; }
      catch (e) { return { stream: null, why: classify(e) }; }
    };
    const both = await tryGet({ video: true, audio: true });
    if (both.stream) return { stream: both.stream, level: "full", reason: "", detail: "" };
    if (both.why === "denied") {
      // a DENIED permission covers both devices; retrying narrower only
      // collects a second refusal
      return { stream: null, level: "none", reason: "denied", detail: EXPLAIN.denied };
    }
    const vid = await tryGet({ video: true, audio: false });
    const aud = await tryGet({ video: false, audio: true });
    if (vid.stream && aud.stream) {
      for (const t of aud.stream.getTracks()) vid.stream.addTrack(t);
      return { stream: vid.stream, level: "full", reason: "", detail: "" };
    }
    if (aud.stream) return { stream: aud.stream, level: "audio", reason: vid.why,
                             detail: "no camera — joining with sound only" };
    if (vid.stream) return { stream: vid.stream, level: "video", reason: aud.why,
                             detail: "no microphone — joining with picture only" };
    return { stream: null, level: "none", reason: both.why || aud.why,
             detail: (EXPLAIN[both.why || aud.why] || EXPLAIN.failed)
                     + " — joining to watch and listen" };
  }

  /* ── bitrate sharing ─────────────────────────────────────────────────────
   * A mesh sends the camera once PER OTHER PARTICIPANT, so upload grows with
   * the room while the uplink does not. Each connection is capped, and the
   * cap shrinks as the room grows. Pure, so it can be tested without a
   * browser. */
  const MESH_TOTAL_KBPS = 1200;   // what we ask of a home uplink, in total
  const MESH_FLOOR_KBPS = 80;     // below this video is worse than useless

  function meshBitrateFor(peerCount, uplinkKbps) {
    const n = Math.max(1, Number(peerCount) || 1);
    const budget = Number(uplinkKbps) > 0
      ? Math.min(uplinkKbps * 0.8, MESH_TOTAL_KBPS) : MESH_TOTAL_KBPS;
    return Math.round(Math.max(MESH_FLOOR_KBPS, Math.min(900, budget / n))) * 1000;
  }

  async function capBitrate(pc, bps) {
    for (const sender of pc.getSenders()) {
      if (!sender.track || sender.track.kind !== "video") continue;
      const params = sender.getParameters();
      if (!params.encodings || !params.encodings.length) params.encodings = [{}];
      params.encodings[0].maxBitrate = bps;
      try { await sender.setParameters(params); } catch (e) { /* older browser */ }
    }
  }

  /* ── the mesh ───────────────────────────────────────────────────────── */
  const POLL_MS = 1000;

  function createMesh({ room, api, iceServers, onLocal, onRemote, onLeave,
                        onState, onError, onMedia }) {
    const base = "/api/learn/rtc/" + encodeURIComponent(room);
    const ICE = iceServers && iceServers.length ? iceServers
      : [{ urls: ["stun:stun.l.google.com:19302"] }];
    const peers = new Map();    // peerId -> {pc, polite, makingOffer, ignoreOffer}
    let selfId = null;
    let local = null;
    let mediaLevel = null;
    let poller = null;
    let stopped = false;

    const say = (m) => { try { onState && onState(m); } catch (e) {} };
    const oops = (e) => { try { onError && onError(String((e && e.message) || e)); } catch (x) {} };

    async function getLocal() {
      if (local || mediaLevel) return local;
      const got = await acquireMedia();
      mediaLevel = got.level;
      local = got.stream;
      if (local && onLocal) onLocal(local);
      // its own callback, not onState: two kinds of message, two channels
      if (got.level !== "full" && onMedia) onMedia(got);
      return local;
    }

    function connection(peerId) {
      let p = peers.get(peerId);
      if (p) return p;
      const pc = new RTCPeerConnection({ iceServers: ICE });
      // politeness must be the SAME on both sides and opposite to each
      // other; comparing ids gives exactly that
      p = { pc, polite: selfId < peerId, makingOffer: false, ignoreOffer: false };
      peers.set(peerId, p);
      if (local) for (const t of local.getTracks()) pc.addTrack(t, local);
      // whatever we could not SEND we must still declare we want to RECEIVE,
      // or a peer with no camera negotiates a connection carrying nothing
      const sending = new Set((local ? local.getTracks() : []).map((t) => t.kind));
      if (!sending.has("video")) pc.addTransceiver("video", { direction: "recvonly" });
      if (!sending.has("audio")) pc.addTransceiver("audio", { direction: "recvonly" });
      pc.ontrack = (e) => {
        const stream = (e.streams && e.streams[0]) || new MediaStream([e.track]);
        onRemote && onRemote(peerId, stream);
      };
      pc.onicecandidate = (e) => { if (e.candidate) send(peerId, { candidate: e.candidate }); };
      pc.onnegotiationneeded = async () => {
        try {
          p.makingOffer = true;
          await pc.setLocalDescription();
          send(peerId, { description: pc.localDescription });
        } catch (e) { oops(e); } finally { p.makingOffer = false; }
      };
      pc.onconnectionstatechange = () => {
        if (["failed", "closed"].includes(pc.connectionState)) drop(peerId);
        else say(peerId + ": " + pc.connectionState);
      };
      return p;
    }

    function send(to, payload) {
      api(base + "/signal", { to, peer: selfId, payload })
        .catch(() => {});   // recovered by the next negotiation, not fatal
    }

    async function handle(from, payload) {
      const p = connection(from);
      const pc = p.pc;
      try {
        if (payload.description) {
          const desc = payload.description;
          const collision = desc.type === "offer"
            && (p.makingOffer || pc.signalingState !== "stable");
          // the impolite peer ignores a colliding offer; the polite yields
          p.ignoreOffer = !p.polite && collision;
          if (p.ignoreOffer) return;
          await pc.setRemoteDescription(desc);
          if (desc.type === "offer") {
            await pc.setLocalDescription();
            send(from, { description: pc.localDescription });
          }
        } else if (payload.candidate) {
          try { await pc.addIceCandidate(payload.candidate); }
          catch (e) { if (!p.ignoreOffer) throw e; }
        }
      } catch (e) { oops(e); }
    }

    function drop(peerId) {
      const p = peers.get(peerId);
      if (!p) return;
      try { p.pc.close(); } catch (e) {}
      peers.delete(peerId);
      onLeave && onLeave(peerId);
    }

    async function poll() {
      if (stopped) return;
      try {
        const r = await api(base + "/poll?peer=" + encodeURIComponent(selfId));
        if (r) {
          for (const m of r.messages || []) await handle(m.from, m.payload);
          const there = new Set(r.peers || []);
          const before = peers.size;
          for (const id of [...peers.keys()]) if (!there.has(id)) drop(id);
          // the LOWER id initiates, so exactly one offer is made per pair
          for (const id of there) {
            if (!peers.has(id)) {
              const p = connection(id);
              if (selfId < id) p.pc.createDataChannel("_");
            }
          }
          // re-share the uplink whenever the room size changes — BOTH ways,
          // or a teacher whose thirty students left would still send as if
          // they were there
          if (peers.size !== before) {
            const bps = meshBitrateFor(peers.size);
            for (const p of peers.values()) capBitrate(p.pc, bps);
          }
        }
      } catch (e) {
        // a 401 means the session that authorised this call is gone: stop
        // knocking rather than polling a server that will never say yes
        if (String(e.message || "").includes("sign in")) { stopped = true; return; }
      }
      if (!stopped) poller = setTimeout(poll, POLL_MS);
    }

    return {
      async join() {
        stopped = false;
        await getLocal();
        const r = await api(base + "/join", {});
        selfId = r.peer;
        say("joined as " + selfId);
        for (const id of r.peers || []) {
          const p = connection(id);
          if (selfId < id) p.pc.createDataChannel("_");
        }
        poll();
        return { selfId, peers: r.peers || [] };
      },
      leave() {
        stopped = true;
        if (poller) clearTimeout(poller);
        for (const id of [...peers.keys()]) drop(id);
        if (local) { for (const t of local.getTracks()) t.stop(); local = null; }
        mediaLevel = null;
        if (selfId) api(base + "/leave", { peer: selfId }).catch(() => {});
        selfId = null;
        say("left");
      },
      // toggling a track's `enabled` keeps the negotiated media line intact —
      // removing it would force a renegotiation just to mute a microphone
      toggle(kind) {
        if (!local) return false;
        const tracks = kind === "video" ? local.getVideoTracks() : local.getAudioTracks();
        if (!tracks.length) return false;
        const on = !tracks[0].enabled;
        for (const t of tracks) t.enabled = on;
        return on;
      },
      has(kind) {
        if (!local) return false;
        return (kind === "video" ? local.getVideoTracks() : local.getAudioTracks()).length > 0;
      },
      enabled(kind) {
        if (!local) return false;
        const t = (kind === "video" ? local.getVideoTracks() : local.getAudioTracks())[0];
        return !!(t && t.enabled);
      },
      get id() { return selfId; },
      get peerIds() { return [...peers.keys()]; },
    };
  }

  window.LinguaMesh = { createMesh, acquireMedia, meshBitrateFor,
                        MESH_TOTAL_KBPS, MESH_FLOOR_KBPS };
})();
