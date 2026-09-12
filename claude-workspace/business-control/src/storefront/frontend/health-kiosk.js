/* The counter kiosk. One job, no sign-in, nothing from the record on
   the screen. A name and a date of birth, or the code on the card —
   from the camera, or from a USB scanner that types. */
(() => {
  const $ = (s) => document.querySelector(s);
  const msg = $("#hk-msg");
  const say = (t) => { msg.textContent = t; };
  const done = (r) => {
    $("#hk-root").innerHTML = `<div class="hk-done">Thank you, ${r.first_name}.<br>
      You're checked in for ${new Date(r.at * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} — please take a seat.</div>`;
    setTimeout(() => location.reload(), 8000);
  };
  const send = async (body) => {
    say("One moment…");
    const r = await fetch("/api/health/kiosk/checkin", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (r.ok) return done(await r.json());
    let m = "Please see the desk.";
    try { m = (await r.json()).detail || m; } catch (e) {}
    say(m);
  };
  $("#hk-go").onclick = () => {
    const name = $("#hk-name").value.trim(), dob = $("#hk-dob").value;
    if (!name || !dob) return say("Your name and your date of birth, please.");
    send({ name, birth_date: dob });
  };
  $("#hk-dob").onkeydown = (e) => { if (e.key === "Enter") $("#hk-go").click(); };
  $("#hk-scan").onclick = async () => {
    if (!window.QRScan || !QRScan.supported()) return say("This screen has no camera; type your name instead.");
    const code = await QRScan.scan({ title: "Show the code on your card" });
    if (code) send({ code });
  };
  if (window.QRScan && QRScan.wedge) QRScan.wedge((code) => send({ code }));
})();
