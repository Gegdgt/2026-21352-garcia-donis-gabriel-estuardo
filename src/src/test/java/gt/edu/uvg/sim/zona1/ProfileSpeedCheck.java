package gt.edu.uvg.sim.zona1;
import java.util.*;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.*;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.PlanCalcScoreConfigGroup.ActivityParams;
import org.matsim.core.config.groups.StrategyConfigGroup.StrategySettings;
import org.matsim.core.controler.*;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.scenario.ScenarioUtils;
public final class ProfileSpeedCheck {
 public static void main(String[] args) throws Exception {
  var c=ConfigUtils.createConfig();
  var out=java.nio.file.Files.createTempDirectory(java.nio.file.Path.of("target"),"profile-speed-");
  c.controler().setOutputDirectory(out.resolve("run").toString());c.controler().setLastIteration(0);
  c.qsim().setEndTime(1500);
  for(String a:List.of("home","work")){var p=new ActivityParams(a);p.setTypicalDuration(3600);p.setScoringThisActivityAtAll(false);c.planCalcScore().addActivityParams(p);}
  var strategy=new StrategySettings();strategy.setStrategyName("KeepLastSelected");strategy.setWeight(1);c.strategy().addStrategySettings(strategy);
  var s=ScenarioUtils.createScenario(c);var n=s.getNetwork();var f=n.getFactory();
  for(int i=0;i<4;i++)n.addNode(f.createNode(Id.createNodeId(i),new Coord(i*1000,0)));
  for(int i=0;i<3;i++){var l=f.createLink(Id.createLinkId(i),n.getNodes().get(Id.createNodeId(i)),n.getNodes().get(Id.createNodeId(i+1)));l.setLength(1000);l.setFreespeed(40);l.setCapacity(10000);l.setNumberOfLanes(1);n.addLink(l);}
  var pf=s.getPopulation().getFactory();int index=0;
  for(String name:List.of("Tortuga","Normal","Liebre")){var p=pf.createPerson(Id.createPersonId(name));p.getAttributes().putAttribute("drivingProfile",name);var plan=pf.createPlan();var home=pf.createActivityFromLinkId("home",Id.createLinkId(0));home.setEndTime(index++*400+1);plan.addActivity(home);plan.addLeg(pf.createLeg("car"));plan.addActivity(pf.createActivityFromLinkId("work",Id.createLinkId(2)));p.addPlan(plan);s.getPopulation().addPerson(p);}
  DrivingProfiles.configure(s);var entered=new HashMap<String,Double>();var durations=new HashMap<String,Double>();
  BasicEventHandler handler=e->{if(e instanceof LinkEnterEvent v && v.getLinkId().toString().equals("1"))entered.put(v.getVehicleId().toString(),v.getTime());if(e instanceof LinkLeaveEvent v && v.getLinkId().toString().equals("1"))durations.put(v.getVehicleId().toString(),v.getTime()-entered.get(v.getVehicleId().toString()));};
  var controller=new Controler(s);controller.addOverridingModule(new AbstractModule(){public void install(){addEventHandlerBinding().toInstance(handler);}});controller.run();
  if(durations.size()!=3)throw new AssertionError(durations);
  double slow=durations.get("Tortuga"),normal=durations.get("Normal"),fast=durations.get("Liebre");
  if(!(slow>normal && normal>fast))throw new AssertionError(durations);
  System.out.println("PASS QSim travel seconds on 1000m free link: "+durations);
  org.apache.logging.log4j.LogManager.shutdown();
 }
}
