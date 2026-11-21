/* One validated metadata request per load; replay windows never supply totals. */
class SimZ1ContinuousHud {
  static validateFreight(payload) {
    const freight=payload.freight_transport, configured=freight?.configured, observed=freight?.observed;
    const fail=detail=>{throw new Error('Servicio de transporte pesado incompatible: '+detail);};
    if(payload.day_observation!=null && (typeof payload.day_observation!=='object' || Array.isArray(payload.day_observation)))
      fail('censo diario inválido');
    const required=Array.isArray(payload.day_observation?.groups) &&
      payload.day_observation.groups.some(row=>row?.family==='pesado');
    if(configured==null && observed==null && !required)return;
    if(!configured || typeof configured.enabled!=='boolean')fail('configuración ausente/inválida');
    if(!configured.enabled) {
      if(observed!=null || required || configured.vehicles_configured!==0)fail('servicio desactivado incompatible');
      return;
    }
    const count=(record,key)=>{
      const value=record?.[key];
      if(!Number.isSafeInteger(value) || value<0)fail('contador '+key);
      return value;
    };
    const ids=(record,key,n,required)=>{
      const value=record?.[key];
      if(value==null && !required)return null;
      if(!Array.isArray(value) || value.length!==n || value.some(x=>typeof x!=='string' || !x) ||
         new Set(value).size!==n)fail('IDs '+key);
      return new Set(value);
    };
    const configuredN=count(configured,'vehicles_configured'), scheduled=count(configured,'departures_scheduled');
    const entered=count(observed,'vehicles_observed'), departed=count(observed,'departures_observed');
    const day=payload.day_observation, policy='fixed-day-24h-v1';
    const fixed=day?.policy===policy || observed?.day_observation_policy===policy;
    const fleet=ids(configured,'fleet_vehicle_ids',configuredN,fixed);
    const seen=ids(observed,'fleet_vehicle_ids',entered,fixed);
    if(fleet && seen && [...seen].some(id=>!fleet.has(id)))fail('flota observada ajena');
    if(!fixed) {
      // Historical full-service contracts still require every scheduled vehicle/departure.
      if(configuredN!==entered || scheduled!==departed)fail('servicio histórico incompleto');
      if(observed.arrivals_observed!=null && count(observed,'arrivals_observed')>entered)
        fail('llegadas históricas incompatibles');
      return;
    }
    if(day?.policy!==policy || observed.day_observation_policy!==policy ||
       day.execution!=='native_day_completed' || day.technical_integrity!=='verified_precleanup_census' ||
       day.coverage_end_seconds!==86400 || payload.source_time_horizon.start_seconds!==0 ||
       payload.source_time_horizon.end_seconds!==86400 || observed.technical_integrity!=='valid' ||
       observed.status!=='valid')fail('censo diario sin respaldo');
    const arrived=count(observed,'arrivals_observed'), active=count(observed,'active_in_traffic_at_cut');
    const waiting=count(observed,'waiting_for_insertion'), unstarted=count(observed,'scheduled_not_departed_at_cut');
    const censored=count(observed,'censored_at_horizon');
    if(!(arrived<=entered && entered<=departed && departed<=scheduled && scheduled===configuredN) ||
       entered!==arrived+active || departed!==entered+waiting || configuredN!==departed+unstarted ||
       censored!==active+waiting+unstarted || count(observed,'active_or_censored')!==censored ||
       count(observed,'missing_departures')!==unstarted || count(observed,'aborted_expeditions')!==0)
      fail('balance de incorporaciones/llegadas/censura');
    const times=(key,n,expected)=>{
      const values=observed[key];
      if(!values || typeof values!=='object' || Array.isArray(values) || Object.keys(values).length!==n ||
         Object.entries(values).some(([id,t])=>!expected.has(id) || !Number.isFinite(t) || t<0 || t>86400))
        fail('evidencia '+key);
      return values;
    };
    // A valid day cannot contain exited_without_arrival (native census integrity rejects it).
    // Counts may coincide; VehicleLeavesTraffic and Arrival times remain separate below.
    const entries=times('observed_traffic_entries',entered,seen), exits=times('observed_traffic_exits',arrived,seen);
    if(Object.entries(exits).some(([id,t])=>t<entries[id]))fail('salida anterior a incorporación');
    const records=observed.completion_records;
    if(!Array.isArray(records) || records.length!==configuredN)fail('censo individual ausente');
    const terminals=observed.terminal_events;
    if(!terminals || typeof terminals!=='object' || Array.isArray(terminals) ||
       Object.keys(terminals).some(id=>!fleet.has(id)))fail('terminales individuales incompatibles');
    const recorded=new Set();let completedRecords=0;
    for(const row of records) {
      if(!row || !fleet.has(row.vehicle_id) || recorded.has(row.vehicle_id) ||
         row.entry_seconds!==(entries[row.vehicle_id] ?? null) ||
         row.traffic_exit_seconds!==(exits[row.vehicle_id] ?? null))fail('censo individual incompatible');
      recorded.add(row.vehicle_id);
      const terminal=terminals[row.vehicle_id], complete=terminal?.status==='completed';
      if(complete ? (!Number.isFinite(terminal.time) || terminal.time<0 || terminal.time>86400 ||
          row.arrival_seconds!==terminal.time || row.traffic_exit_seconds===null ||
          row.traffic_exit_seconds>row.arrival_seconds) :
          (row.arrival_seconds!==null || row.traffic_exit_seconds!==null || terminal &&
            (terminal.status!=='aborted' || !Number.isFinite(terminal.time) || terminal.time<86400)))
        fail('llegada/terminal individual incompatible');
      if(row.trip_outcome!==(complete ? 'completed' : 'censored_at_horizon'))fail('estado individual incompatible');
      completedRecords+=complete;
    }
    if(completedRecords!==arrived)fail('llegadas individuales');
    if(!Array.isArray(day.groups) || day.groups.some(row=>!row || typeof row!=='object' || Array.isArray(row)))
      fail('grupos del censo ausentes');
    const totals={scheduled_requests:0,incorporations:0,real_arrivals:0,completed:0,active_at_cut:0,
      waiting_for_incorporation:0,scheduled_not_departed:0,aborted_before_cut:0}, groups=new Set();
    for(const row of day.groups.filter(row=>row.family==='pesado')) {
      const key=JSON.stringify([row.family,row.od,row.scheduled_hour]);
      if(typeof row.od!=='string' || !row.od || !Number.isSafeInteger(row.scheduled_hour) ||
         row.scheduled_hour<0 || row.scheduled_hour>23 || groups.has(key))fail('grupo duplicado/inválido');
      groups.add(key);
      // Native Counter serializes status categories sparsely; three base counters are mandatory.
      const group={};
      for(const key of Object.keys(totals)) {
        group[key]=(key in row || ['scheduled_requests','incorporations','real_arrivals'].includes(key)) ? count(row,key) : 0;
        totals[key]+=group[key];
      }
      if(group.real_arrivals!==group.completed || group.incorporations!==group.completed+group.active_at_cut ||
         group.scheduled_requests!==group.incorporations+group.waiting_for_incorporation+group.scheduled_not_departed ||
         group.aborted_before_cut!==0)fail('balance del grupo diario');
    }
    const expected={scheduled_requests:configuredN,incorporations:entered,real_arrivals:arrived,completed:arrived,
      active_at_cut:active,waiting_for_incorporation:waiting,scheduled_not_departed:unstarted,aborted_before_cut:0};
    if(Object.keys(totals).some(key=>totals[key]!==expected[key]))fail('conciliación del censo diario');
  }
  static vehicleSummary(payload) {
    const summary=payload?.vehicle_summary;
    if(summary==null)return {private_vehicles:null,public_vehicles:null}; // Historical API without evidence.
    if(summary.schema_version!==1 || typeof summary.temporal_policy!=='boolean')
      throw new Error('Procedencia de vehículos incompatible');
    for(const key of ['private_vehicles','public_vehicles'])
      if(summary[key]!==null && (!Number.isSafeInteger(summary[key]) || summary[key]<0))
        throw new Error('Conteo de vehículos inválido: '+key);
    if(summary.private_vehicles!==null) {
      const basis=summary.temporal_policy ? 'verified_main_cohort_one_vehicle_per_person' : 'verified_private_one_vehicle_per_person';
      const expected=summary.temporal_policy ? payload.counts.principal_cohort_persons : payload.counts.persons_generated;
      if(summary.private_basis!==basis || summary.private_vehicles!==expected)
        throw new Error('Equivalencia particular/vehículo sin respaldo');
    }
    if(summary.public_vehicles!==null) {
      const configured=payload.public_transport?.configured;
      if(summary.public_basis==='explicitly_disabled') {
        if(configured?.enabled!==false || summary.public_vehicles!==0)
          throw new Error('Flota desactivada incompatible');
      } else {
        const ids=configured?.fleet_vehicle_ids;
        if(summary.public_basis!=='unique_configured_fleet_ids' || !Array.isArray(ids) ||
           ids.some(id=>typeof id!=='string' || !id) || new Set(ids).size!==ids.length ||
           summary.public_vehicles!==ids.length || configured.public_transport_vehicles_configured!==ids.length)
          throw new Error('Flota pública única sin respaldo');
      }
    }
    return {private_vehicles:summary.private_vehicles,public_vehicles:summary.public_vehicles};
  }
  constructor(options,hooks={}) {
    this.options=options;this.hooks=hooks;this.sequence=0;this.controller=null;
    this.state={status:'loading',data:null,error:null};
  }
  snapshot() { return {...this.state}; }
  notify() { this.hooks.onState?.(this.snapshot()); }
  checkedWindow(actual,expected,label) {
    if(!actual || typeof actual!=='object' || Array.isArray(actual) ||
       !expected || typeof expected!=='object' || Array.isArray(expected) ||
       !Number.isFinite(actual.start_seconds) || !Number.isFinite(actual.end_seconds) ||
       actual.start_seconds<0 || actual.end_seconds<actual.start_seconds ||
       Object.keys(actual).length!==Object.keys(expected).length ||
       Object.keys(expected).some(key=>!Object.prototype.hasOwnProperty.call(actual,key) || actual[key]!==expected[key]))
      throw new Error('Horizonte de indicadores incompatible: '+label);
  }
  validate(payload,options) {
    if(!payload || typeof payload!=='object' || Array.isArray(payload) || payload.schema_version!==1)
      throw new Error('Esquema de indicadores incompatible');
    if(typeof options.run_id!=='string' || !options.run_id ||
       !Number.isSafeInteger(options.iteration) || options.iteration<0 ||
       typeof options.run_manifest_sha256!=='string' || !options.run_manifest_sha256 ||
       typeof options.source_version!=='string' || !options.source_version ||
       ['run_id','iteration','run_manifest_sha256'].some(key=>payload[key]!==options[key]) ||
       payload.source_version!==options.source_version ||
       (payload.visual_policy ?? null)!==(options.visual_policy ?? null))
      throw new Error('Identidad de indicadores incompatible');
    this.checkedWindow(payload.replay_window,
      {start_seconds:options.start_seconds,end_seconds:options.end_seconds},'replay');
    this.checkedWindow(payload.source_time_horizon,options.source_time_horizon,'fuente');
    this.checkedWindow(payload.metrics_window,options.metrics_window,'conteos');
    const counts=payload.counts;
    if(!counts || typeof counts!=='object' || Array.isArray(counts))
      throw new Error('Conteos de indicadores no disponibles');
    const required=['persons_generated','planned_trips'];
    const optional=['completed_trips','pending_censored_trips','reconstructed_vehicles','vehicles_with_events'];
    for(const key of [...required,...optional]) {
      const value=counts[key];
      if(optional.includes(key) && value===null)continue;
      if(!Number.isSafeInteger(value) || value<0)throw new Error('Conteo de indicadores invalido: '+key);
    }
    if(counts.principal_cohort_persons!=null) {
      for(const key of ['principal_cohort_persons','context_persons','warmup_context_persons','post_context_persons'])
        if(!Number.isSafeInteger(counts[key]) || counts[key]<0)throw new Error('Conteo de cohorte invalido: '+key);
      if(counts.principal_cohort_persons+counts.context_persons!==counts.persons_generated ||
        counts.warmup_context_persons+counts.post_context_persons!==counts.context_persons)
        throw new Error('Balance de poblacion principal/contexto incompatible');
    }
    // No active-QSim estimate is derived from render counts or source totals.
    if(payload.native_active_series!==null)
      throw new Error('Serie de activos nativos sin contrato validado');
    const pt=payload.public_transport?.configured;
    SimZ1ContinuousHud.validateFreight(payload);
    if(pt && (!Number.isSafeInteger(pt.public_transport_vehicles_configured) ||
        pt.public_transport_vehicles_configured<0 || pt.road_demand_persons!==counts.persons_generated))
      throw new Error('Flota pública/N incompatibles');
    SimZ1ContinuousHud.vehicleSummary(payload);
    return payload;
  }
  async load(options=this.options) {
    const sequence=++this.sequence;
    this.controller?.abort();
    this.options={...options,
      source_time_horizon:options.source_time_horizon ? {...options.source_time_horizon} : null,
      metrics_window:options.metrics_window ? {...options.metrics_window} : null};
    const expected=this.options,controller=new AbortController();
    this.controller=controller;
    this.state={status:'loading',data:null,error:null};this.notify();
    if(sequence!==this.sequence)return this.snapshot();
    try {
      const query=new URLSearchParams();
      for(const key of ['run_id','iteration','run_manifest_sha256','start_seconds','end_seconds'])
        query.set(key,String(expected[key]));
      if(expected.source_version!=null)query.set('source_version',expected.source_version);
      if(expected.visual_policy!=null)query.set('visual_policy',expected.visual_policy);
      const endpoint=expected.hud_endpoint || '/api/hud';
      const response=await fetch(endpoint+(endpoint.includes('?') ? '&' : '?')+query,
        {cache:'no-store',signal:controller.signal});
      if(sequence!==this.sequence)return this.snapshot();
      if(!response.ok)throw new Error('HTTP '+response.status+' al cargar indicadores');
      const payload=await response.json();
      if(sequence!==this.sequence)return this.snapshot();
      this.state={status:'ready',data:this.validate(payload,expected),error:null};
      this.notify();
    } catch(error) {
      if(sequence!==this.sequence)return this.snapshot();
      this.state={status:'error',data:null,error:error?.message || 'No se pudieron cargar indicadores'};
      this.notify();
    } finally {
      if(sequence===this.sequence)this.controller=null;
    }
    return this.snapshot();
  }
}
