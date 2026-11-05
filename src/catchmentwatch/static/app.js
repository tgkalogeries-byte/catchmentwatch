const state = { gauges: [] };
const $ = id => document.getElementById(id);
const esc = value => String(value ?? "—").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
function safeSource(value) {
  try { const url = new URL(value); if (url.hostname !== "environment.data.gov.uk" || !["http:","https:"].includes(url.protocol)) return ""; url.protocol = "https:"; return esc(url.href); }
  catch { return ""; }
}
function sourceLink(value, label) {
  const url = safeSource(value);
  return url ? `<a class="source-link" href="${url}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>` : "";
}
function fmtTime(value) {
  if (!value) return "No timestamp";
  const date = new Date(value);
  return Number.isNaN(+date) ? value : date.toLocaleString("en-GB", {dateStyle:"medium",timeStyle:"short",timeZone:"UTC"}) + " UTC";
}
function renderGauges() {
  const query = $("filter").value.trim().toLowerCase();
  const rows = state.gauges.filter(g => [g.name,g.river,g.catchment,g.town].some(v => String(v ?? "").toLowerCase().includes(query)));
  $("gauges").innerHTML = rows.length ? rows.slice(0,350).map(g => {
    const level = g.value === null ? "No reading" : `${Number(g.value).toFixed(3)} ${esc(g.unit)} ${sourceLink(g.source_url,"reading")}`;
    const ref = g.typical_range_high === null ? "No station reference" : `Typical high: ${Number(g.typical_range_high).toFixed(3)} ${esc(g.unit)} ${sourceLink(g.stage_scale_url,"reference")}`;
    const nearby = g.nearby_rainfall;
    const rain = nearby && nearby.value !== null ? `${Number(nearby.value).toFixed(2)} ${esc(nearby.unit)} ${sourceLink(nearby.source_url,"reading")}<span class="sub">${esc(nearby.name)} · ${esc(nearby.distance_km)} km away${nearby.is_stale?" · stale reading":""}</span>` : "No nearby gauge matched";
    const band = g.is_stale ? '<span class="neutral-pill">Stale reading</span>' : g.above_typical_range ? '<span class="signal-pill">Above typical range</span>' : '<span class="neutral-pill">Within / no reference</span>';
    const action = nearby ? `<button class="analyze" type="button" data-level="${esc(g.reference)}" data-rain="${esc(nearby.reference)}">Analyse recent history</button>` : "";
    return `<tr><td><span class="station-name">${esc(g.name)}</span><span class="sub">${esc(g.town)} · ${esc(g.reference)}</span>${action}</td><td>${esc(g.catchment)}<span class="sub">${esc(g.river)}</span></td><td>${level}</td><td>${band}<span class="sub">${ref}</span></td><td>${rain}</td><td>${esc(fmtTime(g.observed_at))}</td></tr>`;
  }).join("") : '<tr><td colspan="6" class="empty">No stations match this filter.</td></tr>';
  document.querySelectorAll(".analyze").forEach(button => button.addEventListener("click", () => analyze(button)));
}
function sparkline(series, field, color, label) {
  const values = series.map(row => Number(row[field]) || 0);
  if (!values.length) return `<div class="chart-empty">No ${esc(label.toLowerCase())} series available.</div>`;
  const min = Math.min(...values), max = Math.max(...values), span = max-min || 1;
  const points = values.map((v,i) => `${10+i*700/Math.max(1,values.length-1)},${110-(v-min)*90/span}`).join(" ");
  return `<div class="spark"><div class="spark-label">${esc(label)} <span>${esc(min.toFixed(2))} – ${esc(max.toFixed(2))}</span></div><svg viewBox="0 0 720 120" role="img" aria-label="${esc(label)} across matched hourly observations"><polyline fill="none" stroke="${color}" stroke-width="2.5" points="${points}"/><line x1="10" y1="111" x2="710" y2="111" stroke="#d7dfdb"/></svg></div>`;
}
function lagChart(profile) {
  const width=720, height=170, zero=82, plot=65, gap=8, barWidth=42;
  const bars=profile.map((item,i)=>{const x=24+i*(barWidth+gap);const value=item.correlation; if(value===null)return `<text x="${x+barWidth/2}" y="151" text-anchor="middle" font-size="10" fill="#667274">—</text>`; const h=Math.abs(value)*plot;const y=value>=0?zero-h:zero;return `<rect x="${x}" y="${y}" width="${barWidth}" height="${Math.max(1,h)}" fill="${value>=0?"#247b68":"#a95117"}"/><text x="${x+barWidth/2}" y="151" text-anchor="middle" font-size="10" fill="#667274">${item.lag_hours}h</text>`;}).join("");
  return `<div class="lag-chart"><div class="spark-label">Rainfall → hourly level change <span>Pearson r by lag · 0–12 hours</span></div><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Pearson correlation across rainfall-to-level-change time lags"><line x1="10" y1="${zero}" x2="710" y2="${zero}" stroke="#8d9995" stroke-dasharray="4 4"/><text x="2" y="18" font-size="10" fill="#667274">+1</text><text x="2" y="${zero+4}" font-size="10" fill="#667274">0</text><text x="2" y="153" font-size="10" fill="#667274">−1</text>${bars}</svg></div>`;
}
async function analyze(button) {
  const mainRow = button.closest("tr");
  const next = mainRow.nextElementSibling;
  if (next?.classList.contains("analysis-row")) { next.remove(); return; }
  button.disabled = true; button.textContent = "Loading history…";
  const detail = document.createElement("tr"); detail.className = "analysis-row";
  detail.innerHTML = '<td colspan="6"><div class="analysis-panel" role="status">Retrieving up to 30 days of archived gauge readings…</div></td>';
  mainRow.after(detail);
  try {
    const params = new URLSearchParams({level_station:button.dataset.level,rain_station:button.dataset.rain,days:"30"});
    const response = await fetch(`/api/pair-analysis?${params}`, {cache:"no-store"});
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `API returned ${response.status}`);
    const best = data.best_lag;
    const finding = best ? `Candidate lag: ${best.lag_hours} hours (training r = ${best.training_correlation.toFixed(2)}; holdout r = ${best.holdout_correlation===null?"not available":best.holdout_correlation.toFixed(2)}). ${data.message}` : data.message;
    detail.innerHTML = `<td colspan="6"><div class="analysis-panel"><div class="analysis-head"><div><span class="eyebrow">TIME ORDERED CHECK / UP TO ${data.period_days} DAYS REQUESTED</span><h3>${esc(finding)}</h3></div><button type="button" class="close-analysis">Close</button></div><p>${esc(data.level_station.name)} / ${esc(data.rain_station.name)} · ${data.matched_hours} overlapping hours · ${data.wet_hours} wet hours across ${data.wet_days} days · ${fmtTime(data.coverage_start)} to ${fmtTime(data.coverage_end)}</p><p class="analysis-split">Earlier training: ${data.training_hours} hours · later holdout: ${data.holdout_hours} hours · same-hour holdout r = ${best?.holdout_concurrent_correlation===null||best?.holdout_concurrent_correlation===undefined?"not available":best.holdout_concurrent_correlation.toFixed(2)}</p><div class="charts">${sparkline(data.series,"rain_mm","#247b68","Hourly rainfall (mm)")}${sparkline(data.series,"level","#295d9b",`River level (${data.level_station.unit||"unit not specified"})`)}${lagChart(data.lag_profile)}</div><p class="analysis-caveat">The candidate lag is selected from the earlier 70% using positive correlations at 1–12 hours, then checked in the later 30%. To call it a repeatable candidate, the holdout correlation must be at least ${data.holdout_screening_rules.minimum_correlation.toFixed(2)} and exceed its same-hour baseline by ${data.holdout_screening_rules.minimum_lift_over_concurrent.toFixed(2)}. These are transparent screening cut-offs, not significance tests. The lag scan does not adjust for multiple comparisons or time-series dependence. This is not a forecast or causal claim. Nearby sensors may not share a catchment. ${sourceLink(data.source_url,"Data and API notes")}</p></div></td>`;
    detail.querySelector(".close-analysis").addEventListener("click",()=>detail.remove());
  } catch(error) {
    detail.innerHTML = `<td colspan="6"><div class="analysis-panel error-panel" role="alert">Historical analysis unavailable: ${esc(error.message)} <button type="button" class="close-analysis">Close</button></div></td>`;
    detail.querySelector(".close-analysis").addEventListener("click",()=>detail.remove());
  } finally { button.disabled = false; button.textContent = "Analyse recent history"; }
}
function renderAlerts(alerts) {
  $("alerts").innerHTML = alerts.length ? alerts.map(a => `<div class="alert-row"><div>${sourceLink(a.url,a.description)}<span class="sub">${esc(a.area)} ${a.county?`· ${esc(a.county)}`:""}</span></div><span class="alert-meta">Severity ${esc(a.severity_level??a.severity??"not supplied")}</span><span class="alert-meta">Raised ${esc(fmtTime(a.time_raised))}</span></div>`).join("") : '<div class="empty">No flood alerts or warnings were returned by the current feed.</div>';
}
function sourceNote(feed) { return feed?.status === "ok" ? `${feed.readings_matched??feed.returned??0} records matched` : "Source unavailable"; }
async function load(refresh=false) {
  const button=$("refresh"); button.disabled=true; button.textContent="Refreshing…";
  try {
    const response=await fetch(`/api/snapshot${refresh?"?refresh=true":""}`,{cache:"no-store"});
    if(!response.ok) throw new Error(`API returned ${response.status}`);
    const data=await response.json(); state.gauges=data.water_levels||[];
    $("updated").textContent=`Fetched ${fmtTime(data.fetched_at)}`; $("alert-count").textContent=data.alerts?.length??"—";
    $("high-count").textContent=state.gauges.filter(g=>g.above_typical_range&&!g.is_stale).length;
    $("water-count").textContent=data.feeds?.water?.readings_matched??"—"; $("rain-count").textContent=data.feeds?.rainfall?.readings_matched??"—";
    $("alert-status").textContent=sourceNote(data.feeds?.alerts); $("water-status").textContent=sourceNote(data.feeds?.water);
    renderGauges(); renderAlerts(data.alerts||[]); const issues=data.partial_errors||[];
    $("error-banner").hidden=!issues.length; $("error-banner").textContent=issues.length?`Some feeds could not be loaded: ${issues.join(" · ")}`:"";
  } catch(error) { $("error-banner").hidden=false; $("error-banner").textContent=`Live data could not be loaded: ${error.message}. Try refreshing, or open the Environment Agency source documentation.`; $("updated").textContent="Live sources unavailable"; }
  finally { button.disabled=false; button.textContent="Refresh sources"; }
}
$("refresh").addEventListener("click",()=>load(true)); $("filter").addEventListener("input",renderGauges); load();
