"""Independent event-to-motion checks, with an explicitly synthetic replay fixture.

Export the small fixture without running QSim:
python scripts/validation/export_visual_motion_fixture.py
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

from simz1_motion import MotionContext
from simz1_trajectories import extract
import visualizador_z1 as viewer


def fixture():
    """Authored native-format event boundaries; never described as a QSim run."""
    links, events, caps, profiles, persons = {}, [], {}, {}, {}

    def event(kind, time, **values):
        events.append(dict(type=kind, time=str(float(time)), **{k:str(v) for k,v in values.items()}))

    cases = [
        ('free', 0, 20, 10., []),
        ('red', 30, 55, 10., [('signal_red',45,54,'MATSim15_QNode_native_branch')]),
        ('stop', 70, 90, 10., [('priority_stop',85,89,'MATSim15_QNode_native_branch')]),
        ('congestion', 100, 130, 10., [('congestion_queue',115,125,'MATSim15_queue_post_step')]),
        ('slow10', 140, 176, 10/3.6, []),
        ('insufficient', 190, 215, None, []),
        ('midnight', 86395, 86415, 10., []),
    ]
    for index,(name,start,end,cap,waits) in enumerate(cases):
        vehicle, person, link = 'vehicle_'+name, 'person_'+name, name+'_a'
        x,y = -90.518+index*.0015,14.636
        links[link] = dict(length=100.,freespeed=10.,from_node=link+'_from',to_node=link+'_to',
                           **{'from':[x,y],'to':[x,y+.0009]})
        if cap is not None:
            caps[vehicle] = cap
        profiles[person],persons[vehicle] = ('Tortuga' if name=='slow10' else 'Normal'),person
        event('departure',start,person=person,link=link)
        event('vehicle enters traffic',start,person=person,vehicle=vehicle,link=link,relativePosition=0)
        for reason,first,last,source in waits:
            for time in range(first,last+1):
                event('simz1NativeDecision',time,vehicle=vehicle,person=person,link=link,
                      decision='WAIT',reason=reason,source=source,lane=link,
                      signalState='RED' if reason=='signal_red' else 'UNSIGNALIZED')
        if name=='red':
            # A consecutive segment must depart from the observed stop without
            # moving either native link transition or changing its route.
            second='red_b'
            links[second]=dict(length=100.,freespeed=10.,from_node=link+'_to',to_node=second+'_to',
                               **{'from':[x,y+.0009],'to':[x,y+.0018]})
            event('left link',end,vehicle=vehicle,link=link)
            event('entered link',end,vehicle=vehicle,link=second)
            end+=20;link=second
        event('vehicle leaves traffic',end,person=person,vehicle=vehicle,link=link,relativePosition=1)
        event('arrival',end,person=person,link=link)
    events.sort(key=lambda row:float(row['time']))
    return links,events,MotionContext(caps,profiles,persons,lanes=False)


def reconstructed():
    links,events,motion=fixture()
    stats={}
    segments=extract(events,links,lambda vehicle:True,viewer.color_velocidad,viewer.GEOD,
                     motion=motion,stats=stats,horizon=86430)
    return links,events,segments,stats


def phase_rows(plan):
    """Read the public compact [t0,t1,s0,v0,a] representation."""
    return [tuple(float(value) for value in row) for row in plan['phases']]


class VisualMotionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from simz1_visual_motion import sample_motion, solve_motion
        cls.sample=staticmethod(sample_motion)
        cls.solve=staticmethod(solve_motion)

    def assert_plan(self, plan, start, end, distance, cap=None):
        phases=phase_rows(plan)
        self.assertTrue(phases)
        self.assertAlmostEqual(phases[0][0],start,places=8)
        self.assertAlmostEqual(phases[-1][1],end,places=8)
        integrated=0.
        for index,(t0,t1,s0,v0,a) in enumerate(phases):
            self.assertTrue(all(math.isfinite(v) for v in (t0,t1,s0,v0,a)))
            self.assertGreaterEqual(t1,t0)
            self.assertAlmostEqual(s0,integrated,places=6)
            v1=v0+a*(t1-t0)
            self.assertGreaterEqual(min(v0,v1),-1e-7)
            if cap is not None:
                self.assertLessEqual(max(v0,v1),cap+1e-7)
            if index:
                self.assertAlmostEqual(phases[index-1][1],t0,places=8)
                if plan['feasible']:
                    previous=phases[index-1]
                    self.assertAlmostEqual(previous[3]+previous[4]*(previous[1]-previous[0]),v0,places=6)
            integrated+=v0*(t1-t0)+.5*a*(t1-t0)**2
        self.assertAlmostEqual(integrated,distance,places=6)
        last=-1e-8
        for index in range(201):
            time=start+(end-start)*index/200
            position,speed=self.sample(plan,time)
            self.assertGreaterEqual(position,last-1e-7)
            self.assertGreaterEqual(position,-1e-7)
            self.assertLessEqual(position,distance+1e-7)
            self.assertGreaterEqual(speed,-1e-7)
            last=position
        self.assertAlmostEqual(self.sample(plan,start)[0],0,places=6)
        self.assertAlmostEqual(self.sample(plan,end)[0],distance,places=6)

    def segments(self):
        _,_,segments,_=reconstructed()
        self.assertTrue(all('Motion_Plan' in segment for segment in segments),
                        'Event reconstruction must apply the visual plan before HTML export')
        return {segment['Link_ID']:segment for segment in segments}

    def test_native_boundaries_routes_measured_speed_and_trip_identity_preserved(self):
        links,events,segments,stats=reconstructed()
        self.assertEqual(len(segments),8)
        self.assertEqual(stats['observed_departures'],7)
        self.assertEqual(stats['reconstructed_vehicles'],7)
        expected={'free_a':(0,20),'red_a':(30,55),'red_b':(55,75),'stop_a':(70,90),
                  'congestion_a':(100,130),'slow10_a':(140,176),'insufficient_a':(190,215),'midnight_a':(86395,86415)}
        for segment in segments:
            start,end=expected[segment['Link_ID']]
            self.assertEqual(segment['timestamps'],[start,end])
            self.assertEqual(segment['Distance_m'],100)
            self.assertAlmostEqual(segment['Speed_kmh'],360/(end-start))
            self.assertEqual(segment['path'],[links[segment['Link_ID']]['from'],links[segment['Link_ID']]['to']])
            self.assertEqual(segment['Trip']['Status'],'completed')
            self.assertFalse(segment['Inferred'])

    def test_no_observed_stop_keeps_continuous_motion_through_residual(self):
        segment=self.segments()['free_a'];plan=segment['Motion_Plan']
        self.assert_plan(plan,0,20,100,10)
        self.assertEqual(segment['Observed_Waits'],{})
        self.assertGreater(self.sample(plan,15)[1],0)
        self.assertLess(self.sample(plan,15)[0],100)

    def test_red_and_stop_decelerate_before_observed_endpoint_then_hold(self):
        for ident,first,end in [('red_a',45,55),('stop_a',85,90)]:
            with self.subTest(link=ident):
                segment=self.segments()[ident];plan=segment['Motion_Plan']
                self.assertTrue(plan['feasible'])
                self.assert_plan(plan,segment['timestamps'][0],end,100,10)
                self.assertTrue(any(row[4]<0 for row in phase_rows(plan)))
                for time in (first,(first+end)/2,end):
                    position,speed=self.sample(plan,time)
                    self.assertAlmostEqual(position,100,places=6)
                    self.assertAlmostEqual(speed,0,places=6)
                self.assertEqual(segment['Movement_End'],first)

    def test_flow_capacity_wait_does_not_locate_vehicle_at_link_end(self):
        segment=self.segments()['congestion_a'];plan=segment['Motion_Plan']
        self.assert_plan(plan,100,130,100,10)
        self.assertEqual(segment['Wait_Evidence'],'native_queue_delay_position_unknown')
        self.assertLess(self.sample(plan,115)[0],100)
        self.assertGreater(self.sample(plan,120)[1],0)
        self.assertNotEqual(plan.get('source'),'native_wait')

    def test_authoritative_ten_kmh_vehicle_never_exceeds_limit(self):
        segment=self.segments()['slow10_a'];plan=segment['Motion_Plan']
        self.assert_plan(plan,140,176,100,10/3.6)
        self.assertEqual(segment['Profile'],'Tortuga')
        for time in (140,145,160,175):
            self.assertAlmostEqual(self.sample(plan,time)[1]*3.6,10,places=6)

    def test_departure_after_native_stop_accelerates_from_zero(self):
        segment=self.segments()['red_b'];plan=segment['Motion_Plan']
        self.assert_plan(plan,55,75,100,10)
        self.assertTrue(plan['feasible'])
        self.assertAlmostEqual(self.sample(plan,55)[1],0,places=6)
        self.assertGreater(self.sample(plan,56)[1],0)
        self.assertTrue(any(row[4]>0 for row in phase_rows(plan)))

    def test_missing_data_preserves_full_interval_without_fabricated_stop(self):
        segment=self.segments()['insufficient_a'];plan=segment['Motion_Plan']
        self.assertEqual(plan['status'],'fallback')
        self.assertTrue(plan['fallback_reason'])
        self.assert_plan(plan,190,215,100)
        self.assertEqual(segment['Observed_Waits'],{})
        self.assertGreater(self.sample(plan,214)[1],0)

    def test_infeasible_fast_interval_is_explicit_and_never_moves_boundaries(self):
        plan=self.solve(100,0,1,0,0,10,1,1)
        self.assertFalse(plan['feasible'])
        self.assertEqual(plan['status'],'unavailable')
        self.assertTrue(plan['fallback_reason'])
        self.assertEqual(plan['phases'],[])
        for time in (0,.5,1):
            self.assertEqual(self.sample(plan,time),(None,None))

    def test_infeasible_braking_fallback_preserves_native_wait_without_claiming_smoothness(self):
        links,events,motion=fixture()
        events.append(dict(type='simz1NativeDecision',time='10',vehicle='vehicle_free',person='person_free',
                           link='free_a',decision='WAIT',reason='signal_red',source='MATSim15_QNode_native_branch'))
        events.sort(key=lambda row:float(row['time']))
        segments=extract(events,links,lambda vehicle:True,viewer.color_velocidad,viewer.GEOD,motion=motion,horizon=86430)
        segment=next(s for s in segments if s['Link_ID']=='free_a');plan=segment['Motion_Plan']
        self.assertEqual(segment['timestamps'],[0,20])
        self.assertEqual(segment['Observed_Waits']['signal_red']['first'],10)
        self.assertEqual(plan['status'],'fallback')
        self.assertIn('infeasible',plan['fallback_reason'])
        self.assertFalse(plan['feasible'])
        self.assert_plan(plan,0,20,100,10)
        self.assertEqual(plan['source'],'native_wait_fallback')
        self.assertAlmostEqual(self.sample(plan,15)[1],0)
        self.assertAlmostEqual(self.sample(plan,15)[0],100)

    def test_impossible_endpoint_time_becomes_gap_instead_of_motion_during_wait(self):
        links,events,motion=fixture()
        events.append(dict(type='simz1NativeDecision',time='5',vehicle='vehicle_free',person='person_free',
                           link='free_a',decision='WAIT',reason='signal_red',source='MATSim15_QNode_native_branch'))
        events.sort(key=lambda row:float(row['time']))
        segments=extract(events,links,lambda vehicle:True,viewer.color_velocidad,viewer.GEOD,motion=motion,horizon=86430)
        segment=next(s for s in segments if s['Link_ID']=='free_a');plan=segment['Motion_Plan']
        self.assertEqual(segment['timestamps'],[0,20])
        self.assertEqual(segment['Observed_Waits']['signal_red']['first'],5)
        self.assertEqual(plan['status'],'unavailable')
        self.assertFalse(plan['feasible'])
        self.assertEqual(plan['phases'],[])
        self.assertEqual(self.sample(plan,15),(None,None))

    def test_disabled_smoothing_still_preserves_observed_red_wait(self):
        links,events,motion=fixture()
        motion.visual_settings['enabled']=False
        segments=extract(events,links,lambda vehicle:True,viewer.color_velocidad,viewer.GEOD,motion=motion,horizon=86430)
        segment=next(s for s in segments if s['Link_ID']=='red_a');plan=segment['Motion_Plan']
        self.assert_plan(plan,30,55,100,10)
        self.assertEqual(segment['timestamps'],[30,55])
        self.assertAlmostEqual(self.sample(plan,50)[0],100)
        self.assertAlmostEqual(self.sample(plan,50)[1],0)

    def test_analytic_triangle_matches_integral_and_velocity_derivative(self):
        # Exactly 100 m in 20 s under +/-1 m/s2 with zero endpoint speeds:
        # the unique maximal-distance solution is the triangle with v(10)=10.
        plan=self.solve(100,0,20,0,0,10,1,1)
        self.assertTrue(plan['feasible'])
        self.assert_plan(plan,0,20,100,10)
        position,speed=self.sample(plan,10)
        self.assertAlmostEqual(position,50,places=6)
        self.assertAlmostEqual(speed,10,places=6)
        for time in (2,7,12,18):
            epsilon=1e-4
            derivative=(self.sample(plan,time+epsilon)[0]-self.sample(plan,time-epsilon)[0])/(2*epsilon)
            self.assertAlmostEqual(derivative,self.sample(plan,time)[1],places=5)

    def test_mathematical_forty_to_zero_reference_has_exact_braking_distance(self):
        initial,deceleration=40/3.6,2.5
        duration=initial/deceleration;distance=initial**2/(2*deceleration)
        plan=self.solve(distance,300,300+duration,initial,0,initial,2,deceleration)
        self.assertTrue(plan['feasible'])
        self.assert_plan(plan,300,300+duration,distance,initial)
        self.assertAlmostEqual(self.sample(plan,300)[1]*3.6,40,places=6)
        self.assertAlmostEqual(self.sample(plan,300+duration)[1],0,places=6)

    def test_midnight_and_reverse_sampling_are_absolute_and_stateless(self):
        plan=self.segments()['midnight_a']['Motion_Plan']
        self.assert_plan(plan,86395,86415,100,10)
        expected={time:self.sample(plan,time) for time in (86395,86400,86405,86410,86415)}
        for time in (86410,86395,86415,86400,86405,86395):
            self.assertEqual(self.sample(plan,time),expected[time])


def export_fixture(destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    links,events,segments,stats=reconstructed()
    _,_,motion=fixture()
    from simz1_visual_motion import solve_motion
    initial,deceleration=40/3.6,2.5
    brake_end=300+initial/deceleration;distance=initial**2/(2*deceleration)
    first=[-90.513,14.639];last=[-90.513,14.639+distance/111111]
    mathematical_trip=dict(Departure=300,Arrival=brake_end+5,Trip_ID='math40:assumed-entry-speed',
        Status='completed',Person_ID='mathematical40',Trip_Index=1,Abort=None,Last_Observed_Time=brake_end+5,
        Observation_End=86430,Origin_Position=first,Destination_Position=last,Origin_Node='math_from',Destination_Node='math_to')
    for name,start,end,length,u,path in [('math40_braking',300,brake_end,distance,initial,[first,last]),
                                        ('math40_hold',brake_end,brake_end+5,0,0,[last,last])]:
        plan=solve_motion(length,start,end,u,0,initial,2,deceleration)
        plan['source']='mathematical_fixture_assumed_entry_speed'
        links[name]=dict(length=length,freespeed=initial,from_node='math_from',to_node='math_to',
                         **{'from':path[0],'to':path[1]})
        segments.append(dict(vehicle='math40',Agent_ID='mathematical40',Link_ID=name,Trip=mathematical_trip,
            Profile='Supuesto matematico: entrada a 40 km/h',Speed_kmh=3.6*length/(end-start),
            color=[255,210,40],path=path,timestamps=[start,end],Inferred=True,Distance_m=length,
            Movement_End=end,Motion_Speed_kmh=3.6*length/(end-start),Observed_Waits={},
            Wait_Evidence='mathematical_fixture_not_observed',Motion_Plan=plan,
            Motion_Provenance=dict(method='mathematical_reference',initial_speed_assumption_mps=u,
                continuous_position_observed=False,vehicle_limit_mps=initial,link_speed_at_entry_mps=initial)))
    root=ET.Element('events',version='1.0')
    for event in events:
        ET.SubElement(root,'event',event)
    ET.indent(root)
    ET.ElementTree(root).write(destination/'fixture-events.xml',encoding='utf-8',xml_declaration=True)
    inputs=dict(vehicle_limits_mps=motion.vehicle_speeds,profiles=motion.profiles,
                vehicle_person_assignments=motion.persons,use_lanes=False,visual_settings=motion.visual_settings,
                source='authored unit fixture, not calibrated vehicle measurements')
    for name,value in [('fixture-network.json',links),('fixture-inputs.json',inputs),
                       ('fixture-trajectories.json',segments),('fixture-stats.json',stats)]:
        (destination/name).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    selection=dict(iteration=0,trajectory_stats=stats,
        selection_warning='FIXTURE SINTETICO: eventos de prueba, no una corrida MATSim ni geometria de campo.',
        manifest=dict(run_id='synthetic-visual-motion-fixture',demand_seed=None,matsim_seed=None,
            counts=dict(planned_persons=7,planned_trips=7),
            results={'0':dict(counts=dict(observed_departures=7))},
            time_horizon=dict(start_seconds=0,end_seconds=86430),
            replay_window=dict(start_seconds=0,end_seconds=86430)))
    viewer.generar_html_animado(segments,links,selection=selection,output=destination/'fixture-replay.html')
    checks=r'''
    // Explicit synthetic QA overlay, injected only in this fixture HTML.
    paused=true;toggle.textContent='Reproducir';
    const motionPanel=document.createElement('div');motionPanel.id='motion-fixture-panel';
    motionPanel.style.cssText='position:fixed;right:14px;top:54px;z-index:1000;background:#071321ee;border:1px solid #6ca4ce;color:#e5f3ff;padding:12px;max-width:410px;font:12px monospace;border-radius:8px';
    const motionTitle=document.createElement('div');motionTitle.textContent='PRUEBAS VISUALES SINTETICAS · no son eventos de campo';motionPanel.appendChild(motionTitle);
    const motionResult=document.createElement('pre');motionResult.id='motion-fixture-result';
    motionResult.style.cssText='white-space:pre-wrap;color:#a4ffc0;margin:8px 0';
    motionPanel.appendChild(motionResult);document.body.appendChild(motionPanel);
    let savedMotionSample=null;
    function motionFixtureSample(label,link,time,expect,rate=null){
      paused=true;toggle.textContent='Reproducir';
      const segment=replaySegments.find(row=>row.Link_ID===link);
      seeker.value=time;seeker.oninput();
      if(rate!==null)setSpeed(rate);
      deckInstance.props.onClick({object:segment});render();
      const marker=layers.find(row=>row.id==='trips').props.data.find(row=>row.vehicle===segment.vehicle);
      const plan=segment.Motion_Plan;
      const phase=plan.phases.find(row=>time>=row[0]&&time<row[1])||plan.phases[plan.phases.length-1];
      const velocity=marker?.Visual_Speed_kmh;
      let pass=!!marker&&Number.isFinite(velocity)&&marker.position.every(Number.isFinite);
      if(expect==='brake')pass=pass&&phase[4]<0&&velocity>0;
      if(expect==='forty')pass=pass&&Math.abs(velocity-40)<1e-5;
      if(expect==='wait')pass=pass&&Math.abs(velocity)<1e-7&&marker.Waiting&&marker.color.every(v=>v===255);
      if(expect==='accel')pass=pass&&phase[4]>0&&velocity>0;
      if(expect==='slow')pass=pass&&Math.abs(velocity-10)<1e-5&&marker.color.join(',')==='245,65,65';
      if(expect==='fallback')pass=pass&&plan.status==='fallback'&&!!plan.fallback_reason;
      if(expect==='midnight')pass=pass&&current>86400&&formatClock(current).includes('dia 2');
      if(expect==='reverse'&&savedMotionSample)pass=pass&&marker.position.every((v,i)=>Math.abs(v-savedMotionSample[i])<1e-10);
      if(expect==='save')savedMotionSample=marker?.position.slice();
      if(rate!==null)pass=pass&&speed===rate&&current===time;
      motionResult.textContent=(pass?'PASS':'FAIL')+' '+label+'\nt='+current.toFixed(6)+' s | '+formatClock(current)+
        '\nVelocidad del marcador: '+(velocity==null?'no disponible':velocity.toFixed(4)+' km/h')+
        '\nPosicion real dibujada: '+JSON.stringify(marker?.position)+
        '\nColor: '+JSON.stringify(marker?.color)+' | fase a='+(phase?.[4]??'n/a')+' m/s2'+
        '\nEstado: '+plan.status+' | '+plan.source+
        '\nMotivo fallback: '+(plan.fallback_reason||'ninguno')+
        '\nIntervalo conservado: '+JSON.stringify(segment.timestamps)+' | media: '+segment.Speed_kmh.toFixed(3)+' km/h'+
        '\nReferencia a/b: '+JSON.stringify(plan.reference_acceleration_mps2??plan.acceleration_mps2??'ver procedencia')+'/'+JSON.stringify(plan.reference_deceleration_mps2??plan.deceleration_mps2??'ver procedencia')+
        '\nPerfil: '+segment.Profile+' | reproduccion '+speed+'x';
      motionResult.dataset.result=pass?'pass':'fail';
    }
    const fixtureRed=replaySegments.find(row=>row.Link_ID==='red_a');
    const fixtureAccel=replaySegments.find(row=>row.Link_ID==='red_b');
    const brakePhase=fixtureRed.Motion_Plan.phases.find(row=>row[4]<0);
    const finalBrakePhase=fixtureRed.Motion_Plan.phases.filter(row=>row[4]<0).slice(-1)[0];
    const accelPhase=fixtureAccel.Motion_Plan.phases.find(row=>row[4]>0);
    const samplePhase=(phase,fraction,otherwise)=>phase?phase[0]+(phase[1]-phase[0])*fraction:otherwise;
    const mathBrake=replaySegments.find(row=>row.Link_ID==='math40_braking');
    const mathHold=replaySegments.find(row=>row.Link_ID==='math40_hold');
    const fixtureActions=[
      ['Freno inicio',()=>motionFixtureSample('Freno inicio','red_a',samplePhase(brakePhase,.1,40),'brake')],
      ['Freno final',()=>motionFixtureSample('Freno final','red_a',samplePhase(finalBrakePhase,.9,44),'brake')],
      ['Espera inmovil',()=>motionFixtureSample('Espera roja observada','red_a',50,'wait')],
      ['Aceleracion',()=>motionFixtureSample('Aceleracion despues de espera','red_b',samplePhase(accelPhase,.5,56),'accel')],
      ['Lento 10 rojo',()=>motionFixtureSample('Lento 10 km/h, rojo','slow10_a',160,'slow')],
      ['Datos insuficientes',()=>motionFixtureSample('Datos insuficientes, fallback','insufficient_a',200,'fallback')],
      ['Medianoche',()=>motionFixtureSample('Tiempo absoluto dia 2','midnight_a',86405,'midnight')],
      ['Guardar muestra',()=>motionFixtureSample('Guardar muestra antes de seek','free_a',12,'save')],
      ['Retroceder',()=>{seeker.value=86405;seeker.oninput();motionFixtureSample('Retroceso restaura posicion','free_a',12,'reverse');}],
      ['Misma muestra 1x',()=>motionFixtureSample('Muestra invariante a 1x','free_a',12,'none',1)],
      ['Misma muestra 120x',()=>motionFixtureSample('Muestra invariante a 120x','free_a',12,'none',120)],
      ['40 km/h supuesto',()=>motionFixtureSample('40 km/h inicial supuesto matematico','math40_braking',300,'forty')],
      ['40 hacia cero',()=>motionFixtureSample('Freno matematico 40 hacia cero','math40_braking',mathBrake.timestamps[1]-.1,'brake')],
      ['Cero matematico',()=>motionFixtureSample('Cero matematico tras freno','math40_hold',(mathHold.timestamps[0]+mathHold.timestamps[1])/2,'wait')]
    ];
    for(const [label,action]of fixtureActions){const button=document.createElement('button');button.textContent=label;button.onclick=action;button.style.cssText='margin:2px;padding:5px';motionPanel.appendChild(button);}
    fixtureActions[0][1]();
    '''
    html_path=destination/'fixture-replay.html'
    html=html_path.read_text(encoding='utf-8')
    marker='\nrender(); requestAnimationFrame(animate);'
    if html.count(marker)!=1:
        raise ValueError('Cannot safely inject fixture QA controls')
    html_path.write_text(html.replace(marker,marker+checks),encoding='utf-8')
    inputs={name:hashlib.sha256((destination/name).read_bytes()).hexdigest() for name in
            ('fixture-events.xml','fixture-network.json','fixture-inputs.json','fixture-trajectories.json','fixture-replay.html')}
    report=dict(source='synthetic_native_format_fixture_not_a_QSim_run',generator=Path(__file__).name,
                command="python scripts/validation/export_visual_motion_fixture.py --output-dir '"+
                        str(destination).replace("'", "''")+"'",
                command_argv=['python','scripts/validation/export_visual_motion_fixture.py',
                              '--output-dir',str(destination)],
                purpose='Event-boundary conservation and visual-phase integration only; geometry and waits are authored test data.',
                cases=['free','red','stop','congestion','slow10','post_stop_acceleration','insufficient','midnight'],
                event_agents=7,mathematical_reference_agents=1,segments=len(segments),
                mathematical_reference='40 km/h initial speed is an explicit solver assumption, absent from native event fixture.',sha256=inputs)
    (destination/'fixture-provenance.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


def fixture_main(argv=None):
    """Reusable export CLI; the authored fixture implementation remains unique."""
    parser=argparse.ArgumentParser(description='Export the synthetic visual-motion fixture without QSim')
    parser.add_argument('--output-dir',type=Path,default=Path('runtime/validation/visual-motion-fixture'))
    args=parser.parse_args(argv)
    export_fixture(args.output_dir)


if __name__=='__main__':
    if len(sys.argv) in (2,3) and sys.argv[1]=='--export-fixture':
        fixture_main(['--output-dir',sys.argv[2]] if len(sys.argv)==3 else [])
    else:
        unittest.main()
