// Read-only UI evidence: phase labels and body offsets follow actual state data.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { roofComparisonData, roofContactPhase, roofStudyData, roofStudyHTML } from '../src/roof-study.ts';

assert.equal(roofContactPhase(['lower-wall', 'lower-wall', 'lower-wall', null]), 'approach');
assert.equal(roofContactPhase(['roof', 'roof', 'lower-wall', 'roof']), 'under_roof');
assert.equal(roofContactPhase(['upper-wall', 'roof', 'lower-wall', null]), 'lip_transition');
assert.equal(roofContactPhase(['upper-wall', 'upper-wall', null, 'upper-wall']), 'exit');
assert.equal(roofContactPhase(['upper-wall', 'other-panel', null, null]), 'unknown');

const panels = [
  { id:'lower-wall', label:'before',origin:[0,0,0],rotation_deg:[0,0,0],width:4.8,height:2.1 },
  { id:'roof', label:'roof',origin:[0,2.1,0],rotation_deg:[90,0,0],width:4.8,height:.8 },
  { id:'upper-wall', label:'exit',origin:[0,2.1,.8],rotation_deg:[0,0,0],width:4.8,height:1.3 },
];
const lower = { placement_id:'lower',contact_id:'main' }, roof = { placement_id:'roof',contact_id:'main' }, upper = { placement_id:'upper',contact_id:'main' };
const request = {setting_design:{wall_profile:'roof'}, scene:{angle_deg:0,wall_panels:panels,inventory:[]}};
const candidate = {id:'test',placements:[{id:'lower',wall_panel_id:'lower-wall'},{id:'roof',wall_panel_id:'roof'},{id:'upper',wall_panel_id:'upper-wall'},{id:'child',mount:{parent_id:'upper',face_id:'face'}}],states:[
  {id:'s0',contacts:{LH:lower,RH:lower,LF:lower,RF:lower}},
  {id:'r1',contacts:{LH:null,RH:lower,LF:lower,RF:lower}},
  {id:'s1',contacts:{LH:roof,RH:lower,LF:lower,RF:lower}},
  {id:'r2',contacts:{LH:null,RH:lower,LF:lower,RF:lower}},
  {id:'s2',contacts:{LH:upper,RH:roof,LF:lower,RF:roof}},
  // A legitimate retreat must make the UI return to the previous contact region.
  {id:'s3',contacts:{LH:roof,RH:roof,LF:lower,RF:roof}},
  {id:'s4',contacts:{LH:upper,RH:{placement_id:'child',contact_id:'main'},LF:upper,RF:upper}},
],events:[
  {limb:'LH',from_state:'s0',release_state:'r1',to_state:'s1'},
  {limb:'LH',from_state:'s1',release_state:'r2',to_state:'s2'},
  {limb:'LH',from_state:'s2',release_state:'none',to_state:'s3'},
  {limb:'LF',from_state:'s3',release_state:'none',to_state:'s4'},
]};
const evaluation = {candidate_id:'test',poses:[{state_id:'s2',status:'pass',joints:{pelvis:[.2,1.7,1],left_shoulder:[0,2,.95],right_shoulder:[.4,2,.95]}}]};
const analysis = {moves:[{event_index:1,prior_load:123.4,fresh_burden:42,effective_burden:78,accumulated_load:145,burden:78}]};
const data = roofStudyData(request,candidate,evaluation,analysis);
assert.deepEqual(data.segments.map(item=>item.phase),['approach','under_roof','lip_transition','under_roof','exit']);
assert.equal(data.transitions[0].eventIndex,1);
assert.deepEqual(data.states[4].move,analysis.moves[0], 'display carries existing numerical evidence, never recalculates fatigue');
assert.ok(Math.abs(data.states[4].pelvis[1]+.4)<1e-9 && Math.abs(data.states[4].pelvis[2]-.2)<1e-9);
assert.ok(Math.abs(data.states[4].shoulders[1]+.1)<1e-9 && Math.abs(data.states[4].shoulders[2]-.15)<1e-9);
assert.equal(data.firstExit.state.id,'s4', 'mounted child resolves parent panel');
assert.equal(roofStudyData(request,candidate,undefined,analysis),undefined,'stale revision has no derived evidence');
assert.equal(roofStudyData(request,candidate,{...evaluation,candidate_id:'old'},analysis),undefined,'wrong evaluation cannot supply a pose');
assert.equal(roofStudyData(request,{...candidate,layout_report:{status:'no_sequence'}},evaluation,analysis),undefined,'layout draft is not a completed roof route');
assert.equal(roofStudyData(request,candidate,{...evaluation,poses:[{...evaluation.poses[0],status:'unknown'}]},analysis).states[4].pelvis,undefined,'unsolved pose cannot display fabricated body coordinates');
const html = roofStudyHTML(request,candidate,evaluation,analysis,4,false);
assert.ok(html.includes('123.4') && html.includes('78.0') && html.includes('42.0'),'unbounded load values are preserved, without clipping to 100');
assert.ok(html.includes('data-step="3"') && html.includes('data-step="4"'),'release and landing controls point to actual state ids');
assert.ok(html.includes('本态骨架与墙板：未检查'),'IK success alone is never reported as a collision pass');
const crossingEvaluation={...evaluation,checks:[{id:'skeleton_wall',state_id:'s2',status:'fail',evidence:{violations:[{panel_id:'roof'}]}}]};
assert.ok(roofStudyHTML(request,candidate,crossingEvaluation,analysis,4,false).includes('存在穿墙，需复核'),'crossing evidence is explicit even with a solved pose');
assert.ok(roofStudyHTML(request,candidate,{...evaluation,checks:[{id:'skeleton_wall',state_id:'s2',status:'pass'}]},analysis,4,false).includes('未检出穿墙'),'pass is scoped to skeleton centre lines');

// Whole-scene rotation must not change offsets measured in the exit wall frame.
const angle=30*Math.PI/180;
const rotatedEvaluation=structuredClone(evaluation);
Object.entries(rotatedEvaluation.poses[0].joints).forEach(([key,p])=>{rotatedEvaluation.poses[0].joints[key]=[p[0],p[1]*Math.cos(angle)-p[2]*Math.sin(angle),p[1]*Math.sin(angle)+p[2]*Math.cos(angle)];});
const rotated=roofStudyData({...request,scene:{...request.scene,angle_deg:30}},candidate,rotatedEvaluation,analysis);
data.states[4].pelvis.forEach((value,index)=>assert.ok(Math.abs(value-rotated.states[4].pelvis[index])<1e-9));

let savedPaths=0, savedStates=0, completeSavedRoof=false;
const bundle=JSON.parse(fs.readFileSync(process.argv[2] || new URL('../../fixtures/wall-roof-bundle.json',import.meta.url),'utf8'));
const paths=[], primary=[];
for(const main of bundle.candidates) {
  const report=main.setting_report;
  paths.push({candidate:main,evaluation:bundle.evaluations.find(item=>item.candidate_id===main.id)});
  if(report) paths.push({candidate:report.baseline_candidate,evaluation:report.baseline_evaluation},...report.allowed_alternatives);
  const comparison=roofComparisonData(main,report);
  if(!comparison) continue;
  const currentEvaluation=bundle.evaluations.find(item=>item.candidate_id===main.id);
  const exitStates=currentEvaluation.mechanics_report.states.filter(item=>report.result.exit_support.state_ids.includes(item.state_id));
  assert.equal(exitStates.filter(item=>item.status==='feasible').length,report.result.exit_support.feasible_states,'exit summary counts actual mechanical states');
  assert.equal(exitStates.filter(item=>item.is_release && item.status==='feasible').length,report.result.exit_support.release_feasible_states,'exit release summary retains pre-move support failures');
  const firstMove=main.events[report.result.exit_support.first_exit_event_index];
  assert.equal(report.result.exit_support.state_ids[0],firstMove.release_state,'exit window starts before the first hand lands on the exit');
  const rendered=roofStudyHTML(bundle.request,main,currentEvaluation,currentEvaluation.design_analysis,0,false,report,'after');
  for(const change of comparison.unusedChanges) assert.ok(rendered.includes(change.placement_id),'skipped modified hold remains explicitly described');
  if(report.selection_role==='exit_support_tradeoff') {
    assert.ok(rendered.includes('出口支撑与全程消耗的取舍'));
    assert.equal(comparison.transferDelta,main.events.length-report.baseline_candidate.events.length,'transfer delta follows the actual independent paths, including zero or negative changes');
    const effortSum = evaluation => evaluation.design_analysis.moves.reduce((sum,move)=>sum+move.proxy_effort,0);
    assert.ok(Math.abs(comparison.effortDelta-(effortSum(currentEvaluation)-effortSum(report.baseline_evaluation)))<1e-4,'effort delta follows evaluated paths');
    if(!report.changes.length && comparison.transferDelta===0 && comparison.effortDelta===0) {
      assert.ok(rendered.includes('当前保留原布局。'),'unchanged layout is explicitly retained without claiming improvement');
      assert.equal(comparison.unusedChanges.length,0,'no unmade adjustment receives credit');
    }
    for(const [transferDelta,effortDelta] of [[-1,-10],[0,0],[2,10]]) {
      const variedReport=structuredClone(report);
      variedReport.result.summary.transfers=variedReport.baseline.summary.transfers+transferDelta;
      variedReport.result.summary.total_proxy_effort=variedReport.baseline.summary.total_proxy_effort+effortDelta;
      const varied=roofStudyHTML(bundle.request,main,currentEvaluation,currentEvaluation.design_analysis,0,false,variedReport,'after');
      assert.ok(varied.includes(`转换次数变化 ${transferDelta>=0?'+':''}${transferDelta}`));
      assert.ok(varied.includes(`模型总负荷变化 ${effortDelta>=0?'+':''}${effortDelta.toFixed(1)}`),'cost changes are signed data, never inferred from the scenario title');
    }
  }
  primary.push({candidate_id:main.id,role:report.selection_role,exit_feasible:report.result.exit_support.feasible_states,exit_states:report.result.exit_support.states,exit_release_feasible:report.result.exit_support.release_feasible_states,exit_release_states:report.result.exit_support.release_states,transfers:report.result.summary.transfers,total_proxy_effort:report.result.summary.total_proxy_effort,unused_changed_ids:comparison.unusedChanges.map(change=>change.placement_id)});
}
for(const item of paths) {
  const evidence=roofStudyData(bundle.request,item.candidate,item.evaluation,item.analysis||item.evaluation.design_analysis);
  if(item.candidate.layout_report) {assert.equal(evidence,undefined);continue;}
  assert.ok(evidence,'completed saved path renders actual roof observations');
  for(const state of evidence.states) {
    const pose=item.evaluation.poses.find(pose=>pose.state_id===state.state.id);
    if(state.pelvis) assert.equal(pose.status,'pass');
    if(state.move) assert.equal(item.candidate.events[state.move.event_index].to_state,item.candidate.states.find(s=>s.id===item.candidate.events[state.move.event_index].to_state).id);
  }
  completeSavedRoof=true;savedPaths++;savedStates+=evidence.states.length;
}
console.log(JSON.stringify({status:'pass',saved_paths:savedPaths,saved_states:savedStates,complete_saved_roof:completeSavedRoof,checks:['contact-derived phases can repeat','release and landing bind to actual states','mounted child inherits wall panel','verified IK only','exit frame invariant to global wall angle','fatigue numbers preserve existing analysis','missing or stale evaluation hides observations','old no_sequence remains a layout','IK pass does not imply skeleton collision pass','two primary variants show local support and whole-route costs','exit window includes the pre-transfer release','modified but unused exit hold is not assigned causal credit'],primary_candidates:primary},null,2));
