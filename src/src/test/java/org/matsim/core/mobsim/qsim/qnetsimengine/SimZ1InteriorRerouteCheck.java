package org.matsim.core.mobsim.qsim.qnetsimengine;
import java.nio.file.Path;
import java.util.*;
import org.matsim.api.core.v01.Id;
import org.matsim.core.events.EventsUtils;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1TerminalTurnCheck.*;
/** Ordinary receipt clearance remains a commitment when rerouting. */
public final class SimZ1InteriorRerouteCheck {
 public static void main(String[] args) {try {
  var s=scenario(Path.of("scenarios/zona1"));
  var l=new SimZ1CorridorOccupancy(s,Set.of(),EventsUtils.createEventsManager());
  SimZ1CorridorOccupancy.install(s.getConfig().qsim(),l);
  var straight=List.of("osm_381097546_0_forward","osm_381097546_1_forward","osm_381097546_2_forward","osm_381097546_3_forward");
  var turn=List.of("osm_381097546_0_forward","osm_381097546_0_backward","osm_381097538_0_forward","osm_381097538_1_forward","osm_381097538_2_forward","osm_381097538_3_forward");
  var longTurn=new ArrayList<>(turn);longTurn.addAll(1,List.of("osm_381097546_1_forward","osm_381097546_1_backward"));
  var v=body(s,"generic-motorcycle",2.1,straight);
  check(l.activity(v,id(straight.get(0)),straight.get(0)+".original",1),"Straight full receipt unavailable");
  check(SimZ1CorridorOccupancy.replacementIssue(s.getConfig().qsim(),v.getId(),straight.stream().map(Id::createLinkId).toList(),0)==null,"Ordinary route rejected");
  check("occupancy_reserved_receipt_clearance".equals(SimZ1CorridorOccupancy.replacementIssue(s.getConfig().qsim(),v.getId(),turn.stream().map(Id::createLinkId).toList(),0)),"Reroute invalidated the clearance used for ordinary receipt admission");
  check(SimZ1CorridorOccupancy.replacementIssue(s.getConfig().qsim(),v.getId(),longTurn.stream().map(Id::createLinkId).toList(),0)==null,"Long receivable return rejected");
  l.release(v.getId(),2,"arrival");
  var prefix=List.of("osm_406843605_32_forward","osm_406843605_33_forward");
  var enteredStraight=new ArrayList<>(prefix);enteredStraight.addAll(straight);
  var shortCandidate=new ArrayList<>(prefix);shortCandidate.addAll(turn);
  var longCandidate=new ArrayList<>(prefix);longCandidate.addAll(longTurn);
  var upstream=body(s,"generic-upstream",2.1,enteredStraight);
  check(l.activity(upstream,id(prefix.get(0)),prefix.get(0)+".original",3),"Upstream full origin unavailable");
  check("occupancy_incompatible_passage_signals".equals(SimZ1CorridorOccupancy.replacementIssue(s.getConfig().qsim(),upstream.getId(),shortCandidate.stream().map(Id::createLinkId).toList(),0)),
        "Short upstream return crossed exclusive calle/avenida phases without a receiver");
  check(SimZ1CorridorOccupancy.replacementIssue(s.getConfig().qsim(),upstream.getId(),longCandidate.stream().map(Id::createLinkId).toList(),0)==null,"Upstream receivable return rejected");
  l.release(upstream.getId(),4,"arrival");SimZ1CorridorOccupancy.uninstall(s.getConfig().qsim());
  System.out.println("PASS ordinary reroute preserves committed entry clearance; full receiver detour remains available");
 }finally{org.apache.logging.log4j.LogManager.shutdown();}}
}
