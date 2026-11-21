// Prepared for user execution. No browser or server, no historical replay writes.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const Catalog=vm.runInNewContext(fs.readFileSync(path.join(__dirname,'simz1_visual_lanes.js'),'utf8')+'\nSimZ1VehicleCatalog');
const catalog=JSON.parse(fs.readFileSync(path.join(__dirname,'../scenarios/zona1/agent-types-road-v1.json'),'utf8'));
for(const [kind,spec] of Object.entries(catalog.profiles)) {
  const record={Agent_ID:'preserve-person',vehicle:'preserve-vehicle',Trip:{Trip_ID:'preserve-trip'},
    Agent_Schema:catalog.schema_version,Agent_Type:kind,Vehicle_Type:spec.vehicle_type,
    Driving_Profile:spec.driving_profile,Vehicle_Dimensions:spec.dimensions,Vehicle_PCU:spec.pcu};
  const before=JSON.stringify(record),result=Catalog.resolve(record);
  assert.equal(result.label,spec.label);
  assert.equal(result.family,({carro:'car',moto:'motorcycle',pesado:'truck'})[spec.family]);
  assert.equal(result.driving_profile.toLowerCase(),spec.driving_profile);
  assert.equal(result.dimensions.length_m,spec.dimensions.length_m);
  assert.equal(result.dimensions.width_m,spec.dimensions.width_m);
  assert.equal(result.dimensions.assumed,true);assert.equal(result.body_model,'rigid');
  assert.equal(JSON.stringify(record),before);
  const alternate=Catalog.resolve({...record,Vehicle_PCU:99});
  assert.equal(JSON.stringify(alternate.dimensions),JSON.stringify(result.dimensions));
}
for(const Profile of ['Normal','Liebre','Tortuga']) {
  assert.equal(Catalog.resolve({Profile}).family,'car');
  assert.equal(Catalog.resolve({Vehicle_Type:Profile}).family,'car');
}
assert.equal(Catalog.resolve({Vehicle_Type:'unrecognized'}).family,'unknown');
assert.equal(Catalog.resolve({Agent_Type:'TransportePublico'}).dimensions,null);
console.log('PASS future catalog labels, independent dimensions/PCU and historical identities; no simulation.');
