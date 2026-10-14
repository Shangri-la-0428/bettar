// Verify that force arrows use the same world contacts as the actual renderer,
// and that only successful equilibrium solutions carry drawable forces.
// Read-only: fixtures are prepared by the backend acceptance workflow.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { contactFrame } from '../src/placement-geometry.ts';

const add = (a,b) => a.map((value,index) => value+b[index]);
const sub = (a,b) => a.map((value,index) => value-b[index]);
const cross = (a,b) => [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const length = a => Math.hypot(...a);
const dot = (a,b) => a.reduce((sum,value,index) => sum+value*b[index],0);
const vector = a => Array.isArray(a) && a.length===3 && a.every(Number.isFinite);
let maxPointError = 0, maxNormalError = 0, forceContacts = 0, feasible = 0, infeasible = 0, unknown = 0, checkedPaths = 0, maxForceResidual = 0, maxTorqueResidual = 0;
const totals = [];
const wallTotals = [];
function verify(request, candidate, evaluation, label) {
  const report = evaluation.mechanics_report;
  assert.ok(report, `${label}: mechanics report required`);
  assert.equal(evaluation.candidate_id, candidate.id, `${label}: evaluation bound to candidate`);
  const states = new Map(candidate.states.map(state => [state.id,state]));
  assert.equal(report.states.length, candidate.states.length, `${label}: includes every release and contact state`);
  const context = { angleDeg:request.scene.angle_deg, inventory:request.scene.inventory, placements:candidate.placements, wallPanels:request.scene.wall_panels };
  for (const result of report.states) {
    const state = states.get(result.state_id);
    assert.ok(state, `${label}/${result.state_id}: state exists`);
    const active = Object.entries(state.contacts).filter(([,contact]) => contact).map(([limb])=>limb).sort();
    assert.deepEqual([...result.active_contacts].sort(),active,`${label}/${state.id}: active limb parity`);
    assert.equal(result.is_release,candidate.events.some(event=>event.release_state===state.id),`${label}/${state.id}: release state parity`);
    if (result.status === 'feasible') {
      feasible++;
      assert.ok(vector(result.com_world_m) && vector(result.gravity_force_n),`${label}/${state.id}: solved centre of mass and gravity`);
      assert.equal(result.contacts.length,active.length,`${label}/${state.id}: every support has a force`);
      assert.ok(result.capacity_utilization <= 1+1e-6, `${label}/${state.id}: inside assumed axial capacity`);
    } else if(result.status === 'infeasible') infeasible++; else unknown++;
    let netForce = result.gravity_force_n ? [...result.gravity_force_n] : [0,0,0], netTorque = [0,0,0];
    for (const contact of result.contacts) {
      const ref = state.contacts[contact.limb];
      assert.ok(ref && ref.placement_id===contact.placement_id,`${label}/${state.id}: no force on released or different hold`);
      const placement = candidate.placements.find(item=>item.id===contact.placement_id), hold = request.scene.inventory.find(item=>item.id===placement.inventory_id);
      const rendered = contactFrame(placement,hold,context,ref.contact_id);
      const pointError = length(sub(rendered.origin,contact.point_world_m)), normalError = length(sub(rendered.normal,contact.normal_world));
      maxPointError = Math.max(maxPointError,pointError); maxNormalError = Math.max(maxNormalError,normalError);
      assert.ok(pointError < 1e-6 && normalError < 1e-6,`${label}/${state.id}/${contact.limb}: arrow contact frame parity`);
      if(result.status!=='feasible') {
        assert.equal(contact.force_world_n,null,`${label}/${state.id}: unsuccessful solve cannot expose drawable force`);
        continue;
      }
      assert.ok(vector(contact.force_world_n),`${label}/${state.id}: finite solved force`); forceContacts++;
      netForce=add(netForce,contact.force_world_n);
      netTorque=add(netTorque,cross(sub(contact.point_world_m,result.com_world_m),contact.force_world_n));
      const axial=dot(contact.force_world_n,contact.axial_direction_world);
      const transverse=length(sub(contact.force_world_n,contact.axial_direction_world.map(value=>value*axial)));
      assert.ok(Math.abs(axial-contact.axial_force_n)<1e-3,`${label}/${state.id}: UI axial value uses declared force axis`);
      assert.ok(Math.abs(transverse-contact.tangent_force_n)<1e-3,`${label}/${state.id}: transverse value uses same force axis`);
      assert.ok(contact.capacity_margin_n>=-1e-3,`${label}/${state.id}: accepted force within capacity`);
    }
    if(result.status==='feasible') {
      const forceResidual=length(netForce), torqueResidual=length(netTorque);
      maxForceResidual=Math.max(maxForceResidual,forceResidual); maxTorqueResidual=Math.max(maxTorqueResidual,torqueResidual);
      assert.ok(forceResidual<1e-3 && torqueResidual<1e-3,`${label}/${state.id}: rendered force vectors balance gravity and moments`);
      assert.ok(Math.abs(forceResidual-result.force_residual_n)<1e-3 && Math.abs(torqueResidual-result.torque_residual_nm)<1e-3,`${label}/${state.id}: residual labels match vectors`);
    }
  }
  checkedPaths++;
}
for(const program of ['diagonal_balance','opposing_sidepulls','roof_exit']) {
  const bundle=JSON.parse(fs.readFileSync(new URL(`../../fixtures/setting-${program}-bundle.json`,import.meta.url),'utf8'));
  const candidate=bundle.candidates[0], evaluation=bundle.evaluations.find(item=>item.candidate_id===candidate.id), report=candidate.setting_report;
  verify(bundle.request,candidate,evaluation,`${program}/after`);
  verify(bundle.request,report.baseline_candidate,report.baseline_evaluation,`${program}/before`);
  report.allowed_alternatives.forEach((alternative,index)=>verify(bundle.request,alternative.candidate,alternative.evaluation,`${program}/alternative-${index+1}`));
  totals.push({program,before:report.baseline_evaluation.mechanics_report.summary,after:evaluation.mechanics_report.summary,alternatives:report.allowed_alternatives.length});
}
for(const profile of ['overhang','roof','dihedral','arete']) {
  const bundle=JSON.parse(fs.readFileSync(new URL(`../../fixtures/wall-${profile}-bundle.json`,import.meta.url),'utf8'));
  assert.equal(bundle.request.setting_design.wall_profile,profile,`${profile}: saved wall profile matches`);
  for(const candidate of bundle.candidates) {
    const evaluation=bundle.evaluations.find(item=>item.candidate_id===candidate.id), report=candidate.setting_report;
    const layoutOnly=candidate.layout_report?.status==='no_sequence';
    verify(bundle.request,candidate,evaluation,`wall/${profile}/${layoutOnly ? 'starting-layout' : 'after'}`);
    if(layoutOnly) {
      assert.equal(candidate.states.length,1,`${profile}: layout only contains its actual start state`);
      assert.equal(candidate.events.length,0,`${profile}: no fabricated movement sequence`);
      assert.equal(report,undefined,`${profile}: no completed-route comparison report`);
    } else {
      assert.ok(report,`${profile}: complete result has its comparison evidence`);
      verify(bundle.request,report.baseline_candidate,report.baseline_evaluation,`wall/${profile}/before`);
      report.allowed_alternatives.forEach((alternative,index)=>verify(bundle.request,alternative.candidate,alternative.evaluation,`wall/${profile}/alternative-${index+1}`));
    }
    wallTotals.push({profile,layout_only:layoutOnly,states:candidate.states.length,events:candidate.events.length,summary:evaluation.mechanics_report.summary,alternatives:report?.allowed_alternatives.length ?? 0});
  }
}
assert.ok(feasible>0 && forceContacts>0,'acceptance contains drawable feasible states');
console.log(JSON.stringify({status:'pass',checked_paths:checkedPaths,states:{feasible,infeasible,unknown},force_contacts:forceContacts,max_point_error_m:maxPointError,max_normal_error:maxNormalError,max_rendered_force_residual_n:maxForceResidual,max_rendered_torque_residual_nm:maxTorqueResidual,checks:['state and release binding','renderer contact frame parity','failed solve has no drawable force','axial/transverse values share model axis','rendered forces balance gravity and moment','all four wall experiments, including actual starting state without a complete beta'],programs:totals,wall_profiles:wallTotals},null,2));
