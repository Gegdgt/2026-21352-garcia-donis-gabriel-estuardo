package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.util.*;
import org.apache.commons.lang3.tuple.Pair;
import static org.matsim.core.mobsim.qsim.qnetsimengine.SimZ1StorageFixture.*;

/** Three native component actors, not a controller or a historical replay.
 * The measured length/storage/endpoints of 30262980_10 are used in a synthetic
 * single-slot control. This isolates the owner's admitted clearance from the
 * later downstream blockage; it does not assert the historical queue partition.
 */
public final class SimZ1OrdinaryReceiptClearanceCheck {
    private record NativeLocation(QVehicle vehicle,String link,String queue,String phase) { }
    private static void addLocation(Map<String,List<NativeLocation>> locations,QVehicle vehicle,
                                    String link,String queue,String phase) {
        locations.computeIfAbsent(vehicle.getId().toString(),ignored->new ArrayList<>())
            .add(new NativeLocation(vehicle,link,queue,phase));
    }
    private static void verifyCensusRows(Set<String> expected,Map<String,Map<String,Object>> rows) {
        require(rows.keySet().equals(expected),"Census omitted or invented an actor");
        for(var entry:rows.entrySet()) {
            var row=entry.getValue();String vehicle=entry.getKey();
            require(((Number)row.get("nativeCopies")).intValue()==1,"Expected one native copy: "+vehicle);
            require(Boolean.TRUE.equals(row.get("activeReservation"))&&((Number)row.get("domainCopies")).intValue()==1,
                "Expected one compatible active/domain reservation: "+vehicle);
            require(Objects.equals(row.get("nativeLink"),row.get("routeCurrentLink"))
                &&Objects.equals(row.get("nativeLink"),row.get("reservationLink"))
                &&Objects.equals(row.get("nativeQueue"),row.get("reservationQueue"))
                &&Objects.equals(row.get("corridor"),row.get("expectedCorridor")),"Native/route/reservation mismatch: "+vehicle);
            near(((Number)row.get("footprintMeters")).doubleValue(),((Number)row.get("bodyMeters")).doubleValue()+.1,
                "Census body/gap mismatch: "+vehicle);
            near(((Number)row.get("reservationBodyMeters")).doubleValue(),((Number)row.get("bodyMeters")).doubleValue(),
                "Reserved body differs from native vehicle: "+vehicle);
        }
    }
    private static Map<String,Object> census(SimZ1StorageFixture f,String phase,double now) throws Exception {
        f.safety();var locations=new LinkedHashMap<String,List<NativeLocation>>();
        for(var link:f.links.values()) {
            Collection<QLaneI> queues=link instanceof QLinkLanesImpl lanes?lanes.getQueueLanes().values():List.of(link.getAcceptingQLane());
            for(var lane:queues) {
                var queue=(QueueWithBuffer)lane;String linkId=link.getLink().getId().toString(),queueId=queue.getId().toString();
                for(Object vehicle:(Iterable<?>)field(queue,"vehQueue"))addLocation(locations,(QVehicle)vehicle,linkId,queueId,"travelling");
                for(Object pair:(Iterable<?>)field(queue,"buffer"))addLocation(locations,(QVehicle)((Pair<?,?>)pair).getKey(),linkId,queueId,"buffer");
            }
        }
        var expected=new LinkedHashSet<String>();f.actors.keySet().forEach(v->expected.add(v.toString()));
        require(locations.keySet().equals(expected),"Native census omitted or invented an actor");
        var active=(Map<?,?>)field(f.ledger,"active");require(active.keySet().equals(f.actors.keySet()),"Active reservation census differs from actors");
        var uniqueDomains=Collections.newSetFromMap(new IdentityHashMap<Object,Boolean>());
        uniqueDomains.addAll(((Map<?,?>)field(f.ledger,"domains")).values());
        var domainCopies=new HashMap<String,Integer>();var occupied=new TreeMap<String,Double>();
        for(Object domain:uniqueDomains) {
            var slots=(List<?>)field(domain,"reservations");var used=(double[])field(domain,"used");
            for(int slot=0;slot<slots.size();slot++) {
                double sum=0;
                for(var entry:((Map<?,?>)slots.get(slot)).entrySet()) {
                    Object reservation=entry.getValue(),vehicle=field(reservation,"vehicle");
                    require(active.get(vehicle)==reservation,"Domain body has no matching active reservation");
                    require((int)field(reservation,"slot")==slot&&entry.getKey().equals(field(reservation,"ordinal")),"Reservation slot/ordinal index differs");
                    domainCopies.merge(vehicle.toString(),1,Integer::sum);sum+=(double)field(reservation,"footprint");
                }
                near(used[slot],sum,"Census differs from slot body sum");
                require(sum>=0&&sum<=(double)field(domain,"capacity")+1e-8,"Census exceeds body capacity");
                if(sum>0)occupied.put(field(domain,"id")+"/"+slot,sum);
            }
        }
        require(domainCopies.keySet().equals(expected),"Domain reservation census differs from actors");
        var rows=new LinkedHashMap<String,Map<String,Object>>();
        for(var actor:f.actors.values()) {
            String vehicle=actor.vehicle.getId().toString();var copies=locations.get(vehicle);var location=copies.get(0);
            require(location.vehicle()==actor.vehicle,"Native identity differs from the fixture actor");
            Object reservation=active.get(actor.vehicle.getId());var row=new LinkedHashMap<String,Object>();
            row.put("nativeCopies",copies.size());row.put("activeReservation",reservation!=null);row.put("domainCopies",domainCopies.get(vehicle));
            row.put("nativeLink",location.link());row.put("nativeQueue",location.queue());row.put("nativePhase",location.phase());
            row.put("routeCurrentLink",actor.path.get(actor.index));row.put("reservationLink",field(reservation,"link").toString());
            row.put("reservationQueue",field(reservation,"nativeQueue"));row.put("corridor",field(field(reservation,"domain"),"id"));
            row.put("expectedCorridor",f.ledger.corridorId(id(location.link())));row.put("slot",field(reservation,"slot"));
            row.put("ordinal",field(reservation,"ordinal"));row.put("bodyMeters",actor.vehicle.getVehicle().getType().getLength());
            row.put("reservationBodyMeters",field(reservation,"length"));
            row.put("footprintMeters",field(reservation,"footprint"));row.put("frontMeters",field(reservation,"frontBound"));rows.put(vehicle,row);
        }
        verifyCensusRows(expected,rows);
        long arrivals=f.events.stream().filter(e->e.getEventType().equals("arrival")).count();
        long exits=f.events.stream().filter(e->e.getEventType().equals("vehicle leaves traffic")).count();
        return Map.of("phase",phase,"time",now,"actors",rows,"activeActors",expected.size(),"activeReservations",active.size(),
            "occupiedMetersBySlot",occupied,"nativeNodeMoves",f.moves,"arrivals",arrivals,"trafficExits",exits);
    }
    @SuppressWarnings("unchecked")
    private static List<String> rejectCensusCopies(Map<String,Object> observed) {
        var rows=(Map<String,Map<String,Object>>)observed.get("actors");String vehicle=rows.keySet().iterator().next();var rejected=new ArrayList<String>();
        for(var mutation:Map.of("missing_native",Map.entry("nativeCopies",0),"duplicate_native",Map.entry("nativeCopies",2),
                "missing_reservation",Map.entry("activeReservation",false),"duplicate_reservation",Map.entry("domainCopies",2)).entrySet()) {
            var copy=new LinkedHashMap<String,Map<String,Object>>();rows.forEach((v,row)->copy.put(v,new LinkedHashMap<>(row)));
            copy.get(vehicle).put(mutation.getValue().getKey(),mutation.getValue().getValue());boolean failed=false;
            try {verifyCensusRows(rows.keySet(),copy);}catch(AssertionError expected){failed=true;}
            require(failed,"Corrupt census copy accepted: "+mutation.getKey());rejected.add(mutation.getKey());
        }
        verifyCensusRows(rows.keySet(),rows);return rejected;
    }
    public static void main(String[] args) throws Exception {
        var profile=new Profile("30262980_10 ordinary receipt control",
            new double[]{31.02062790185436},1,26.02052437573696);
        try(var f=new SimZ1StorageFixture(profile,false)) {
            var censuses=new ArrayList<Map<String,Object>>();
            var head=f.actor("body-head-car",4.5,"short0","receipt-a","dest-a");
            var prior=f.actor("body-prior-truck",8,"short0","receipt-a","dest-a");
            var owner=f.through("body-owner-truck",8,"avenue","receipt-a");
            var terminal=f.queue("short0",".lane.0");
            f.seed(head,".lane.0",0);f.ready(terminal,100);
            require(terminal.getFirstVehicle()==head.vehicle,"Head must occupy the native buffer");
            f.seed(prior,".lane.0",100);f.ready(terminal,110);
            require(!terminal.isAcceptingFromUpstream(),"Prior travelling truck must fill native terminal storage");
            near(terminal.getLoadIndicator(),3.5,"Buffered head is excluded from native travel PCU");
            near(f.front(prior),21.42052437573696,"Prior body must remain behind the head");
            f.seed(owner,".lane.1",100);f.ready(f.queue("avenue",".lane.1"),110);
            require(f.query(owner,"short0",111).feasible(),"Ordinary receipt should use the available reserved body space");
            require(f.cross(owner,111),"Owner did not execute native admission");
            f.ready(f.queue("short0",".original"),120);f.split("short0",121);
            near(f.front(owner),6.204125580370871,"Owner must remain at the real original endpoint");
            double clear=f.ledger.entryClearanceDistance(owner.vehicle,id("short0"));
            require(clear>f.front(owner),"Fixture must need terminal progression for clearance");
            long ordinal=(long)field(f.reservation(owner),"ordinal");
            double reserved=f.used("short0",0);
            censuses.add(census(f,"admitted_waiting",121));
            for(double now:new double[]{180,3600,59159}) {
                f.ready(terminal,now);f.split("short0",now);f.ready(f.queue("short0",".original"),now);
                near(f.front(owner),6.204125580370871,"Elapsed time must not invent physical progress");
                require(!f.ledger.crossingCleared(owner.vehicle.getId(),f.ledger.corridorId(id("short0")),clear,111,now),
                    "Elapsed time released an uncleared crossing");
                near(f.used("short0",0),reserved,"Waiting consumed or released reserved body space");
                require((long)field(f.reservation(owner),"ordinal")==ordinal,"Waiting replaced the owner's reservation");
                f.safety();
                censuses.add(census(f,"clock_only_wait",now));
            }
            // A downstream movement is distinct from the owner's entry node.
            // Its actual native admission removes the head; no timeout, manual
            // pop, release or forced move is used to make the queue discharge.
            require(f.cross(head,59160),"Owner's upstream crossing incorrectly blocked the downstream head");
            for(double now=59161;now<=59200;now++) {
                f.timer.setTime(now);f.links.get(id("short0")).doSimStep();f.safety();
            }
            require(f.front(owner)>=clear,"Native terminal progression did not clear the owner's body");
            require(f.ledger.crossingCleared(owner.vehicle.getId(),f.ledger.corridorId(id("short0")),clear,111,59201),
                "Actual body progress failed to release the crossing");
            require((long)field(f.reservation(owner),"ordinal")==ordinal,"Terminal progression replaced the owner's reservation");
            require(f.moves==2,"Expected only the owner's admission and the head's legal downstream movement");
            f.safety();
            var finalCensus=census(f,"owner_cleared_three_actors_still_active",59201);censuses.add(finalCensus);
            var rejected=rejectCensusCopies(finalCensus);
            System.out.println("ORDINARY_RECEIPT_CENSUS "+new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(
                Map.of("checkpoints",censuses,"final",finalCensus,"rejected_copy_mutations",rejected,"copy_scope","validator-only copies; no native state or event mutation")));
            System.out.println("PASS three-actor ordinary receipt evolution: native terminal saturation holds admitted owner; legal downstream head movement frees native storage, preserves FIFO/gap and clears owner; no arrival claimed");
        } finally {org.apache.logging.log4j.LogManager.shutdown();}
    }
}
