package org.matsim.core.mobsim.qsim.qnetsimengine;

import java.lang.reflect.Proxy;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.network.Link;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.mobsim.framework.MobsimDriverAgent;
import org.matsim.core.mobsim.qsim.interfaces.SignalizeableItem;
import org.matsim.core.mobsim.qsim.interfaces.SignalGroupState;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.lanes.Lane;
import org.matsim.vehicles.Vehicle;

/** Calls the pinned native turn logic: disconnected ABORT takes precedence over red WAIT. */
public final class Zona1NativeDecisionCheck {
    public static void main(String[] args) {
        var scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
        var network = scenario.getNetwork();
        for (int i = 0; i < 5; i++) network.addNode(network.getFactory().createNode(Id.createNodeId(i), new Coord(i, 0)));
        var links = new LinkedHashMap<String,Link>();
        int[][] endpoints = {{0,1},{1,2},{3,4}};
        String[] names = {"current", "connected", "disconnected"};
        for (int i = 0; i < names.length; i++) {
            var link = network.getFactory().createLink(Id.createLinkId(names[i]),
                network.getNodes().get(Id.createNodeId(endpoints[i][0])), network.getNodes().get(Id.createNodeId(endpoints[i][1])));
            network.addLink(link); links.put(names[i], link);
        }
        var queueLinks = new HashMap<Id<Link>,QLinkI>();
        for (var link : links.values()) queueLinks.put(link.getId(), (QLinkI) Proxy.newProxyInstance(
            QLinkI.class.getClassLoader(), new Class<?>[]{QLinkI.class}, (proxy, method, values) -> {
                if (method.getName().equals("getLink")) return link;
                throw new AssertionError("Unexpected QLink call: " + method);
            }));
        var qNetwork = new QNetwork(network, null) {
            @Override public Map<Id<Link>,QLinkI> getNetsimLinks() { return queueLinks; }
        };
        var green = new AtomicBoolean(false);
        var lane = (QLaneI) Proxy.newProxyInstance(QLaneI.class.getClassLoader(),
            new Class<?>[]{QLaneI.class, SignalizeableItem.class}, (proxy, method, values) -> switch (method.getName()) {
                case "getId" -> Id.create("lane", Lane.class);
                case "hasGreenForToLink", "hasGreenForAllToLinks" -> green.get();
                case "getLastMovementTimeOfFirstVehicle" -> 0.0;
                default -> throw new AssertionError("Unexpected lane call: " + method);
            });
        var driver = (MobsimDriverAgent) Proxy.newProxyInstance(MobsimDriverAgent.class.getClassLoader(),
            new Class<?>[]{MobsimDriverAgent.class}, (proxy, method, values) -> {
                if (method.getName().equals("getId")) return Id.createPersonId("person");
                throw new AssertionError("Unexpected driver call: " + method);
            });
        var vehicle = (QVehicle) Proxy.newProxyInstance(QVehicle.class.getClassLoader(), new Class<?>[]{QVehicle.class},
            (proxy, method, values) -> switch (method.getName()) {
                case "getDriver" -> driver;
                case "getId" -> Id.create("vehicle", Vehicle.class);
                case "getCurrentLink" -> links.get("current");
                case "getEarliestLinkExitTime" -> 0.0;
                default -> throw new AssertionError("Unexpected vehicle call: " + method);
            });
        var events = EventsUtils.createEventsManager();
        var captured = new ArrayList<Event>();
        events.addHandler((BasicEventHandler)captured::add);
        var diagnostics = new Zona1NativeDiagnostics(scenario, events);
        var logic = new SignalTurnAcceptanceLogic();
        for (String destination : List.of("disconnected", "missing", "null", "connected", "green")) {
            green.set(destination.equals("green"));
            var next = destination.equals("null") ? null : Id.createLinkId(destination.equals("green") ? "connected" : destination);
            var turn = logic.isAcceptingTurn(links.get("current"), lane, next, vehicle, qNetwork, 10);
            var expected = switch (destination) {
                case "connected" -> TurnAcceptanceLogic.AcceptTurn.WAIT;
                case "green" -> TurnAcceptanceLogic.AcceptTurn.GO;
                default -> TurnAcceptanceLogic.AcceptTurn.ABORT;
            };
            if (turn != expected) throw new AssertionError(destination + ": " + turn);
            diagnostics.turn(links.get("current"), lane, next, vehicle, qNetwork, 10, turn, logic);
        }
        var reasons = captured.stream().map(event -> event.getAttributes().get("reason")).toList();
        var expectedReasons = List.of("turn_abort_disconnected", "turn_abort_missing_link", "turn_abort_null_route", "signal_not_green", "turn_go");
        if (!reasons.equals(expectedReasons)) throw new AssertionError("Misclassified native causes: " + reasons);
        var nativeItem = new DefaultSignalizeableItem(Set.of(Id.createLinkId("connected")));
        var permissions = new LinkedHashMap<SignalGroupState,Boolean>();
        for (var state : SignalGroupState.values()) {
            nativeItem.setSignalStateAllTurningMoves(state);
            boolean permitted = nativeItem.hasGreenForToLink(Id.createLinkId("connected"));
            if (permitted != Zona1NativeDiagnostics.nativePermitsPassage(state))
                throw new AssertionError("Diagnostics disagree with native state permission: " + state);
            permissions.put(state, permitted);
        }
        TurnAcceptanceLogic conflict = (current, currentLane, next, agent, net, time) -> TurnAcceptanceLogic.AcceptTurn.WAIT;
        green.set(true);
        diagnostics.turn(links.get("current"), lane, Id.createLinkId("connected"), vehicle, qNetwork, 11,
            TurnAcceptanceLogic.AcceptTurn.WAIT, conflict);
        if (!captured.get(captured.size() - 1).getAttributes().get("reason").equals("intersection_conflict"))
            throw new AssertionError("A WAIT with native passage permission must not be attributed to red/amber");
        System.out.println("PASS: native disconnected/missing/null ABORT is distinct from signal WAIT and GREEN GO; " + reasons);
        System.out.println("PASS: pinned native color permissions (YELLOW permits clearance): " + permissions);
        org.apache.logging.log4j.LogManager.shutdown();
    }
}
