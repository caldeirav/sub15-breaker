// Optional browser verification. The default refuses to run against a live backend.
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const args=process.argv.slice(2);
function option(name,fallback){const i=args.indexOf(name);return i<0?fallback:args[i+1];}
const live=args.includes("--execute-live");
const url=option("--url","http://127.0.0.1:8092");
const output=option("--output",null);
if(!output||!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(url))throw new Error("New --output and loopback --url required");
mkdirSync(output,{recursive:false});
const token=live?readFileSync(option("--token-file",".infra/live-demo-ui/ui.token"),"utf8").trim():"offline-browser-fixture-token-not-a-platform-credential";
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1500,height:1100}});
const requests=[],errors=[],results=[];
page.on("request",request=>requests.push({method:request.method(),path:new URL(request.url()).pathname}));
page.on("pageerror",error=>errors.push(error.message));
try{
  await page.goto(url);
  await page.getByLabel("UI run token",{exact:true}).fill(token);
  await page.getByRole("button",{name:"Unlock",exact:true}).click();
  await page.waitForFunction(()=>document.querySelector("#login-panel").classList.contains("hidden"));
  const status=await page.evaluate(()=>fetch("/api/live/status").then(r=>r.json()));
  if(!live&&!status.fixture)throw new Error("Fixture verification refuses a live backend");
  if(live&&status.fixture)throw new Error("Live verification refuses fixture evidence");
  if(!status.repeatable||status.budget_enforced)throw new Error("Expected repeatable demo without budget gates");
  for(const card of ["D01","D02","D03","D04","D05"]){
    await page.locator(`button[data-card="${card}"]`).click();
  }
  if(requests.some(r=>r.method==="POST"&&r.path==="/api/live/runs"))throw new Error("Loading/selecting dispatched a run");
  const noRunBeforeClick=true;
  for(const card of ["D01","D02","D03","D04","D05","D01"]){
    await page.locator(`button[data-card="${card}"]`).click();
    await page.waitForFunction(()=>!document.querySelector("#run").disabled);
    const [response]=await Promise.all([
      page.waitForResponse(r=>r.request().method()==="POST"&&new URL(r.url()).pathname==="/api/live/runs"),
      page.getByRole("button",{name:"Run both routes",exact:true}).click()
    ]);
    if(response.status()!==202)throw new Error(`Run rejected: ${response.status()}`);
    const initial=await response.json();
    if(!live&&results.length===0){
      for(const arm of ["classifier","llm"]){
        await page.locator(`#${arm} .result`).filter({hasText:"Latest startup observation:"}).waitFor();
        if(await page.locator(`#${arm} .lane-status`).textContent()!=="Startup")throw new Error("Startup lane is still labelled waiting");
      }
      if(!await page.locator("#system-events").evaluate(e=>e.closest("details").open))throw new Error("Startup progress hidden in collapsed panel");
    }
    // Wait for the rendered terminal state, then read the matching server result.
    // Do not treat an unresolved async predicate as completion.
    await page.waitForFunction(id=>{
      const phase=document.querySelector("#run-phase");
      return phase.dataset.runId===id&&/completed|failed|interrupted/.test(phase.textContent);
    },initial.id,{timeout:live?8100000:15000});
    const result=await page.evaluate(id=>fetch(`/api/live/runs/${id}`).then(r=>r.json()),initial.id);
    results.push(result);
    writeFileSync(`${output}/results.json`,JSON.stringify(results,null,2));
    const label=results.length===6?`${card}-repeat`:card;
    await page.screenshot({path:`${output}/${label}-desktop.png`,fullPage:true});
    if(result.phase!=="completed")throw new Error(`${card} retained terminal failure; no retry authorized`);
    const events=await page.evaluate(async id=>{
      const text=await fetch(`/api/live/runs/${id}/events`).then(r=>r.text());
      return text.split("\n").filter(line=>line.startsWith("data: ")).map(line=>JSON.parse(line.slice(6))).filter(row=>row.sequence);
    },initial.id);
    if(events.some((e,i)=>e.sequence!==i+1))throw new Error("Event sequence gap/duplication");
    const first=events.map((e,i)=>[e,i]).filter(([e])=>e.lane===result.order[0]).map(([,i])=>i);
    const second=events.map((e,i)=>[e,i]).filter(([e])=>e.lane===result.order[1]).map(([,i])=>i);
    if(!first.length||!second.length||Math.max(...first)>=Math.min(...second))throw new Error("Arms not observed sequentially");
    writeFileSync(`${output}/${label}-events.json`,JSON.stringify(events,null,2));
    if(["D04","D05"].includes(card)&&Object.values(result.lanes).some(l=>!l.summary.fault_control||l.summary.timing.guard_whole_review!==null))throw new Error("Fault incorrectly treated as model speed");
  }
  const before=requests.filter(r=>r.method==="POST"&&r.path==="/api/live/runs").length;
  if(!live){
    await page.evaluate(()=>renderProgress({phase:"failed",error:"offline_startup_fixture",lanes:{
      classifier:{phase:"waiting",summary:null},llm:{phase:"waiting",summary:null}}}));
    for(const arm of ["classifier","llm"]){
      if(await page.locator(`#${arm} .lane-status`).textContent()!=="Not completed")throw new Error("Failed startup still appears to be waiting");
    }
  }
  await page.reload();
  await page.getByRole("heading",{name:"Before the action, a decision.",exact:true}).waitFor();
  const after=requests.filter(r=>r.method==="POST"&&r.path==="/api/live/runs").length;
  if(before!==6||after!==before)throw new Error("Unexpected automatic/double execution");
  if(results[0].id===results[5].id||results[0].order[0]===results[5].order[0])throw new Error("Repeat did not create a fresh counterbalanced run");
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:`${output}/mobile.png`,fullPage:true});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2))throw new Error("Mobile page overflows viewport");
  await page.keyboard.press("Tab");
  if(!await page.evaluate(()=>["A","BUTTON","INPUT","SUMMARY"].includes(document.activeElement.tagName)))throw new Error("Keyboard navigation unavailable");
  if(errors.length)throw new Error(`Browser script errors: ${errors.join("; ")}`);
  writeFileSync(`${output}/proof.json`,JSON.stringify({passed:true,mode:live?"live":"explicit_offline_fixture",noRunBeforeClick,
    explicitRunPosts:before,repeatVerified:true,armsSequential:true,responsiveKeyboardChecks:true,pageErrors:errors,
    runIds:results.map(r=>r.id),script_sha256:createHash("sha256").update(readFileSync(new URL(import.meta.url))).digest("hex")},null,2));
  console.log(`Browser checks passed (${live?"live":"offline fixture"}): six explicit runs including a repeat, sequential lanes, no auto execution, desktop/mobile, keyboard, no JS errors. ${output}`);
}finally{await browser.close();}
