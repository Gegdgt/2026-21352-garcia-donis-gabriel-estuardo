'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const Catalog=vm.runInNewContext(fs.readFileSync(path.join(__dirname,'simz1_visual_lanes.js'),'utf8')+'\nSimZ1VehicleCatalog');
const dimensions={length_m:12,width_m:2.5,source:'freight_visual_matches_TuBus_RigidProxy',assumed:true};
const truck=Catalog.resolve({Vehicle_Type:'FreightTruck',Agent_Type:'TransportePesado',Vehicle_Dimensions:dimensions,
  Vehicle_Physical_Dimensions:{length_m:10,width_m:2.5,source:'effective_vehicles',assumed:true}});
const bus=Catalog.resolve({Vehicle_Type:'TransitBus',Vehicle_Dimensions:dimensions});
assert.equal(truck.label,'Camión');assert.equal(truck.family,'truck');
assert.equal(truck.dimensions.length_m,bus.dimensions.length_m);
assert.equal(truck.dimensions.width_m,bus.dimensions.width_m);
assert.equal(truck.physical.dimensions.length_m,10,'physical size must remain separate');
assert.notEqual(truck.family,Catalog.resolve({Vehicle_Type:'Normal'}).family);
assert.notEqual(truck.family,Catalog.resolve({Vehicle_Type:'Motociclista'}).family);
const compact={length_m:8,width_m:2.3,source:'saved_freight_service_dimensions',assumed:true};
const compactTruck=Catalog.resolve({Vehicle_Type:'FreightTruck',Vehicle_Dimensions:compact,
  Vehicle_Physical_Dimensions:{...compact,nature:'configured'}});
assert.equal(compactTruck.label,'Camión');
assert.equal(compactTruck.dimensions.length_m,8);assert.equal(compactTruck.dimensions.width_m,2.3);
assert.equal(compactTruck.physical.dimensions.length_m,8);
assert.ok(compactTruck.dimensions.length_m>Catalog.resolve({Vehicle_Type:'Normal'}).dimensions.length_m);
assert.ok(compactTruck.dimensions.length_m<bus.dimensions.length_m);
const labels={Normal:'Carro',Liebre:'Carro liebre',Tortuga:'Carro Tortuga',Motociclista:'Moto',
  MotocicletaRapida:'Moto Liebre',MotocicletaLenta:'Moto tortuga',
  Transmetro_RigidProxy:'Transmetro',TuBus_RigidProxy:'TuBus'};
for(const [type,label] of Object.entries(labels))assert.equal(Catalog.resolve({Vehicle_Type:type}).label,label);
const publicRecord=Catalog.resolve({Vehicle_Type:'TuBus_RigidProxy',Vehicle_Dimensions:dimensions,
  Trip:{Transit:{operator:'Recorded operator',service_id:'tubus_T1'}}});
assert.equal(publicRecord.operator,'Recorded operator');assert.equal(publicRecord.service,'tubus_T1');
assert.equal(publicRecord.dimensions.length_m,12,'compact freight must not shrink the public fleet');
console.log('PASS historical and compact freight bodies, requested nine labels, separate public geometry and recorded operator');
