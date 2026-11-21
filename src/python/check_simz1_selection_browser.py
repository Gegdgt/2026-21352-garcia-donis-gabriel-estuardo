"""Create an isolated WebGL selection regression page; no simulation or manifest changes.

Open target/prompt9-browser.html in a real browser. Its test buttons exercise the
same input/click callbacks as the production viewer and inspect actual Deck layers.
"""
from pathlib import Path
from visualizador_z1 import generar_html_animado


def main():
    folder=Path(__file__).resolve().parents[1]/'target'
    folder.mkdir(exist_ok=True)
    destination=folder/'prompt9-browser.html'
    origin=[-90.517,14.641];middle=[-90.516,14.642];end=[-90.515,14.643]
    trip=dict(Departure=32390,Arrival=32520,Trip_ID='person:trip:0001',Status='completed',
        Person_ID='person',Trip_Index=1,Abort=None,Last_Observed_Time=32520,Observation_End=86400,
        Origin_Position=origin,Destination_Position=end,Origin_Node='o',Destination_Node='d')
    second=dict(trip,Departure=60000,Arrival=60060,Trip_ID='person:trip:0002',Trip_Index=2,Last_Observed_Time=60060)
    segments=[dict(vehicle='vehicle',Agent_ID='person',Link_ID='l',Profile='Normal',Trip=identity,
        path=path,timestamps=times,Movement_End=times[1],Motion_Speed_kmh=36,Speed_kmh=36,color=[255,210,40])
        for path,times,identity in [( [origin,middle],[32400,32440],trip),([middle,end],[32480,32520],trip),
                                    ([origin,end],[60000,60060],second)]]
    links={'l':dict(**{'from':origin,'to':end},length=310,freespeed=10)}
    generar_html_animado(segments,links,output=destination)
    checks=r'''
    // Browser-only fixture: production controls above are unchanged.
    paused=true; toggle.textContent='Reproducir';
    const testPanel=document.createElement('div');
    testPanel.style.cssText='margin-top:10px;border-top:1px solid #fff;padding-top:8px;max-width:440px;font:13px monospace';
    const testResult=document.createElement('pre');testResult.id='selection-test-result';
    testResult.style.cssText='white-space:pre-wrap;color:#adffb2';
    hud.appendChild(testPanel);testPanel.appendChild(testResult);
    function sample(label,expected) {
      const ids=['selected-history','selected-future','selected-origin','selected-destination'];
      const counts=ids.map(id=>layers.find(layer=>layer.id===id).props.data.length);
      const actual=[...counts,info.style.display==='none'?0:1];
      const pass=JSON.stringify(actual)===JSON.stringify(expected);
      testResult.textContent=(pass?'PASS':'FAIL')+' '+label+'\nt='+current+
        '\nhistoria/futuro/origen/destino/panel = '+actual.join('/')+
        '\nEsperado: '+expected.join('/');
      testResult.dataset.result=pass?'pass':'fail';
      return pass;
    }
    function seek(time){seeker.value=time;seeker.oninput();}
    const actions=[
      ['Seleccionar viaje',()=>{seek(32420);deckInstance.props.onClick({object:replaySegments[0]});sample('seleccion',[1,2,1,1,1]);}],
      ['Llegada exacta 32520',()=>{seek(32520);sample('arrival exclusiva',[0,0,0,0,0]);}],
      ['Despues 32521',()=>{seek(32521);sample('despues de llegada',[0,0,0,0,0]);}],
      ['Retroceder 32490',()=>{seek(32490);sample('retroceso restaura',[2,1,1,1,1]);}],
      ['Hueco 32460',()=>{seek(32460);sample('hueco conserva viaje',[1,1,1,1,1]);}],
      ['Segundo viaje 60020',()=>{seek(60020);sample('no transferencia entre viajes',[0,0,0,0,0]);}],
      ['Limpiar fondo',()=>{deckInstance.props.onClick({object:null});sample('limpieza',[0,0,0,0,0]);}]
    ];
    for(const [label,action] of actions){const button=document.createElement('button');button.textContent=label;button.onclick=action;testPanel.appendChild(button);}
    actions[0][1]();
    '''
    html=destination.read_text(encoding='utf-8')
    html=html.replace('render(); requestAnimationFrame(animate);','render(); requestAnimationFrame(animate);'+checks)
    destination.write_text(html,encoding='utf-8')
    print(destination)


if __name__=='__main__':main()
