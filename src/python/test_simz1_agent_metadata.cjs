// The selection labels expose only explicitly recorded categories; no browser.
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync('python/visualizador_z1_controls.js', 'utf8');
const start = source.indexOf('function agentMetadataText(');
const end = source.indexOf('function tooltipText(', start);
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(source.slice(start, end), sandbox);
const labels = value => sandbox.agentMetadataText(value);
for (const category of ['Normal', 'Motociclista', 'Liebre', 'Tortuga', 'TransportePublico', 'TransportePesado']) {
  assert.ok(labels({Agent_Type: category, Agent_Schema: 'simz1-six-v1'}).includes('Tipo de agente: '+category));
}
const historical = labels({Profile: 'Normal'});
assert.ok(historical.includes('Tipo de agente: No registrado'));
assert.ok(!historical.includes('Tipo de agente: Normal'));
const motorcycle = labels({Agent_Type: 'Motociclista', Vehicle_Type: 'Motociclista',
  Vehicle_Type_Source: 'effective_vehicles', Vehicle_PCU: .25});
assert.ok(motorcycle.includes('PCU registrado: 0.25'));
assert.ok(motorcycle.includes('Tipo vehicular: Motociclista'));
assert.ok(labels({Agent_Type: 'TransportePublico'}).includes('Tipo vehicular: No registrado'));
console.log('PASS: six explicit agent types, distinct vehicle PCU, no historical relabeling or invented passenger bus');
