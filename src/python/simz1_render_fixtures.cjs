// Synthetic, in-memory renderer inputs. Never reads or writes a scientific run.
'use strict';
const {harness}=require('./test_simz1_continuous_replay.cjs');
const scale=6371008.8*Math.PI/180,xy=(x,y)=>[x/scale,y/scale];
function createFixture(count,mode='dense',{busEvery=0}={}) {
  const links={},segments=[],trips={},events=[];
  for(let i=0;i<count;i++) {
    const road=Math.floor(i/30),id='road-'+road,lane=i%3,rank=Math.floor(i%30/3),vehicle='car-'+String(i).padStart(5,'0');
    const y=road*30,path=mode==='turn' ? [xy(0,y),xy(600,y),xy(600,y+600)] : [xy(0,y),xy(1200,y)];
    if(!links[id])links[id]={path,num_lanes:3,length_m:1200,lane_width_m:3,offset_eligible:true,opposing_lanes:0,
      from_node:'from-'+road,to_node:'to-'+road,allowed_to_links:[],osm_tags:{name:'Calle fixture '+road},
      native_lanes:Object.fromEntries([0,1,2].map(index=>[id+'.'+index,{index,represented_lanes:1,start_m:1200}]))};
    const waiting=mode==='dense',start=waiting ? -100+rank*.01 : -40+rank*3,end=115,hold=20;
    const motion={version:1,status:'kinematic',distance_m:1200,
      phases:waiting ? [[start,hold,0,1200/(hold-start),0],[hold,end,1200,0,0]] : [[start,end,0,1200/(end-start),0]]};
    if(waiting){motion.hold_start=hold;motion.native_wait_boundary=hold;}
    const record={vehicle,Agent_ID:vehicle,Profile:'Normal',Replay_Journey_Key:vehicle,Link_ID:id,path:[path[0],path.at(-1)],
      timestamps:[start,end],Motion_Plan:motion,Speed_kmh:30,Max_Speed_kmh:40,
      Observed_Waits:waiting ? {signal_red:{first:hold,last:114,position_evidence:'queue_exit'}} : {}};
    segments.push(record);trips[vehicle]={Trip_ID:vehicle,Person_ID:vehicle,Departure:start,Arrival:end,Status:'completed'};
    if(busEvery>0 && i%busEvery===0) {
      const driver='synthetic-driver-'+i,departure='synthetic-departure-'+i;
      Object.assign(record,{Agent_ID:null,Driver_ID:driver,Profile:'No disponible',Vehicle_Family:'bus',Vehicle_Type:'synthetic-bus-type',
        Vehicle_Dimensions:{length_m:12,width_m:2.5,source:'synthetic-benchmark-assumption',assumed:true}});
      Object.assign(trips[vehicle],{Person_ID:null,Driver_ID:driver,
        Trip_ID:'transit:'+JSON.stringify([vehicle,'synthetic-line','synthetic-route',departure]),
        Transit:{schema:'simz1-transit-replay-v1',vehicle_id:vehicle,driver_id:driver,line_id:'synthetic-line',route_id:'synthetic-route',
          departure_id:departure,domain_scope:'synthetic_fixture',route_links:[id],activity_intervals:[],
          source:{schedule_sha256:'a'.repeat(64),vehicles_sha256:'b'.repeat(64)},terminal_status:'service_finished',
          service_end_confirmed:true,completion_source:'native_driver_arrival_after_traffic_exit'}});
    }
    events.push({vehicle,link:id,lane:id+'.'+lane,type:'entered lane',time:start});
  }
  // This synthetic benchmark owns the complete roster. Supply the same
  // explicit closure contract as the production SQLite endpoint; absence of
  // that contract correctly means unknown predecessors, not a packed queue.
  const keys=segments.map(r=>JSON.stringify([r.vehicle,r.Replay_Journey_Key,r.Link_ID,r.timestamps]));
  const keysByRoad=new Map();
  segments.forEach((r,i)=>{if(!keysByRoad.has(r.Link_ID))keysByRoad.set(r.Link_ID,[]);keysByRoad.get(r.Link_ID).push(keys[i]);});
  const queue_context={schema_version:1,policy:'native-hold-closure-v1',segments,transition_segments:[],trips,lane_events:events,
    by_seed:Object.fromEntries(keys.map((key,i)=>[key,{complete:true,reason:null,record_keys:keysByRoad.get(segments[i].Link_ID)}]))};
  return {geometry:{schema_version:1,available:true,links},payload:{segments,trips,queue_context,lane_replay:{events},
    signal_replay:{series:[{system_id:'s',group_id:'g',states:[[0,'RED'],[60,'GREEN'],[90,'RED']]}]}}};
}
async function loadFixture(count,mode,options={}) {
  const fixture=createFixture(count,mode,options),h=harness({},fixture.geometry);
  h.api.pause();h.reply(0,fixture.payload);
  // Drain only cooperative preparation slices in the fake UI scheduler.
  for(let round=0;round<1000 && h.api.getState().buffering;round++) {
    await new Promise(resolve=>setImmediate(resolve));
    for(const [id,timer] of h.timers)if(timer.delay===0){h.timers.delete(id);timer.fn();}
  }
  if(h.api.getState().buffering)throw new Error('Fixture preparation did not finish');
  if(h.api.getState().error)throw new Error(h.api.getState().error);
  h.api.seek(30);
  h.sandbox.deckInstance.getViewports=()=>[{width:1200,height:800,project:p=>[50+p[0]*scale/2,700-p[1]*scale/2]}];
  h.sandbox.deckInstance.props.onViewStateChange({viewState:{...h.sandbox.deckInstance.props.viewState,longitude:0,latitude:0,zoom:17}});
  return {h,fixture};
}
module.exports={createFixture,loadFixture};
