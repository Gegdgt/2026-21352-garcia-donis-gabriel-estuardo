package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.nio.file.Path;
import java.util.*;
import org.matsim.api.core.v01.Id;
import org.matsim.core.events.EventsUtils;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1TerminalTurnCheck.*;

/** An installed reroute must not require mutually exclusive phases before
 * the body has any place to stop. A detour with a full receiver remains legal. */
public final class SimZ1SignalCycleRouteCheck {
    public static void main(String[] args) {
        try {
            var s=scenario(Path.of(args.length==0?"scenarios/zona1":args[0]));
            var ledger=new SimZ1CorridorOccupancy(s,Set.of(),EventsUtils.createEventsManager());
            SimZ1CorridorOccupancy.install(s.getConfig().qsim(),ledger);
            var base=List.of("osm_420120096_3_forward","osm_420120096_4_forward","osm_420120096_5_forward",
                    "osm_420120096_6_forward","osm_420120096_7_forward","osm_420120096_8_forward");
            var shortDetour=new ArrayList<>(base);
            shortDetour.addAll(3,List.of("osm_381097546_5_backward","osm_381097546_5_forward"));
            var longDetour=new ArrayList<>(shortDetour);
            longDetour.addAll(4,List.of("osm_381097546_4_backward","osm_381097546_4_forward"));
            for(var path:List.of(base,shortDetour,longDetour))for(int i=1;i<path.size();i++)
                check(s.getNetwork().getLinks().get(id(path.get(i-1))).getToNode()==
                      s.getNetwork().getLinks().get(id(path.get(i))).getFromNode(),"Disconnected fixture");
            var car=body(s,"generic-body",4.5,base);
            check(ledger.activity(car,id(base.get(0)),base.get(0)+".original",1),"Initial full-body origin unavailable");
            check(SimZ1CorridorOccupancy.replacementIssue(s.getConfig().qsim(),car.getId(),base.stream().map(Id::createLinkId).toList(),0)==null,"Ordinary route rejected");
            check("occupancy_incompatible_passage_signals".equals(SimZ1CorridorOccupancy.replacementIssue(s.getConfig().qsim(),car.getId(),shortDetour.stream().map(Id::createLinkId).toList(),0)),
                    "Reroute installed an uninterruptible return through mutually exclusive signal phases");
            check(SimZ1CorridorOccupancy.replacementIssue(s.getConfig().qsim(),car.getId(),longDetour.stream().map(Id::createLinkId).toList(),0)==null,"Detour with a full-body receiver was rejected");
            ledger.release(car.getId(),2,"arrival");
            SimZ1CorridorOccupancy.uninstall(s.getConfig().qsim());
            System.out.println("PASS incompatible short signal cycle rejected; ordinary route and longer receivable detour retained");
        } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
