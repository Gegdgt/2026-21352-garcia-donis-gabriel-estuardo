package gt.edu.uvg.sim.zona1;

import javax.inject.Inject;
import javax.inject.Provider;
import com.google.inject.Injector;
import com.google.inject.Key;
import com.google.inject.name.Names;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.controler.AbstractModule;
import org.matsim.core.controler.Controler;
import org.matsim.core.router.util.LinkToLinkTravelTime;
import org.matsim.core.router.util.TravelTime;
import org.matsim.core.trafficmonitoring.TravelTimeCalculator;
import java.util.List;
import org.matsim.api.core.v01.Scenario;
import org.matsim.core.router.RoutingModule;
import org.matsim.core.population.routes.RouteUtils;

/** Use observed link times (including queues and red lights) for subsequent ReRoute plans. */
public final class ExperiencedTimeRouting {
    private ExperiencedTimeRouting() { }
    public static void configure(Controler controler) {
        var config = controler.getConfig();
        // Controler's standard TravelTimeCalculatorModule consumes enter/leave events.
        // Do not install a second calculator or replace it with free-flow link times.
        config.travelTimeCalculator().setCalculateLinkTravelTimes(true);
        var routing=ConfigUtils.addOrGetModule(config,Zona1RoutingConfigGroup.class);
        String policy=DrivingProfiles.validatePolicy(routing.getRoutingPolicy());
        // Do not silently repair incompatible options or alter stuck interventions.
        SimZ1Configuration.validate(config);
        config.travelTimeCalculator().setTraveltimeBinSize(60);
        if (config.qsim().getEndTime().isDefined()) {
            int end = (int)Math.ceil(config.qsim().getEndTime().seconds());
            config.travelTimeCalculator().setMaxTime(Math.max(config.travelTimeCalculator().getMaxTime(),end));
        }
        controler.addOverridingModule(new AbstractModule() {
            @Override public void install() {
                bindCarTravelDisutilityFactory().toInstance(times->DrivingProfiles.costs(times,policy));
                // Keep the standard event calculator; normalize its output on PHYSICAL links.
                // Both routing costs and the routing clock then use exactly the same seconds.
                addTravelTimeBinding("car").toProvider(new Provider<TravelTime>() {
                    @Inject Injector injector;
                    @Override public TravelTime get() {
                        TravelTimeCalculator calculator=config.travelTimeCalculator().getSeparateModes()
                            ?injector.getInstance(Key.get(TravelTimeCalculator.class,Names.named("car")))
                            :injector.getInstance(TravelTimeCalculator.class);
                        return DrivingProfiles.expectedTimes(calculator.getLinkTravelTimes());
                    }
                });
                if (config.travelTimeCalculator().isCalculateLinkToLinkTravelTimes()) {
                    bind(LinkToLinkTravelTime.class).toProvider(new Provider<LinkToLinkTravelTime>() {
                        @Inject TravelTimeCalculator calculator;
                        @Override public LinkToLinkTravelTime get() {
                            return DrivingProfiles.expectedTurns(calculator.getLinkToLinkTravelTimes());
                        }
                    });
                }
                bind(org.matsim.core.network.algorithms.NetworkTurnInfoBuilderI.class)
                    .toInstance(() -> new SimZ1RouteSafety(controler.getScenario()).allowedTurnInfos());
                // TripRouter and the standard ReRoute PlanRouter both resolve this
                // car binding. Pair TurnInfos remain a connectivity policy only.
                addRoutingModuleBinding("car").toProvider(new Provider<RoutingModule>() {
                    @Inject Injector injector;
                    @Override public RoutingModule get() {
                        var times=injector.getInstance(Key.get(TravelTime.class,Names.named("car")));
                        var turns=config.travelTimeCalculator().isCalculateLinkToLinkTravelTimes()
                            ?injector.getInstance(LinkToLinkTravelTime.class):null;
                        return sequenceRouting(controler.getScenario(),times,turns,policy);
                    }
                });
            }
        });
    }

    /** Bounded replacement of the link-to-link routing module; same physical
     * time/disutility policy, including experienced turn times and person costs.
     * Also callable by focused tests without constructing a Controller or QSim.
     */
    static RoutingModule sequenceRouting(Scenario scenario,TravelTime times,LinkToLinkTravelTime turns,String policy) {
        var safety=new SimZ1RouteSafety(scenario);
        safety.tripOd().bindPlans(scenario);
        var router=new SimZ1TurnRouter(scenario.getNetwork(),safety,times,turns,policy);
        return request -> {
            var from=request.getFromFacility().getLinkId();
            var to=request.getToFacility().getLinkId();
            var person=request.getPerson();
            double departure=request.getDepartureTime();
            // MATSim's original LinkToLinkRoutingModule passes no vehicle here.
            // Person profile costs still apply; PlanRouter preserves the old ID.
            var contract=safety.tripOd().forRequest(request);
            var path=router.path(from,to,departure,person,null,null,Double.NaN,List.of(from),contract);
            if (path==null) throw new IllegalStateException("No sequence/OD-legal car route from "+from+" to "+to);
            if (contract!=null && contract.validate(path)!=null) throw SimZ1TripOd.invalid("invalid routing result");
            var estimate=router.evaluate(path,departure,person,null,Double.NaN);
            var route=RouteUtils.createNetworkRoute(path);
            route.setTravelTime(estimate.seconds()); route.setTravelCost(estimate.cost());
            route.setDistance(path.size()==1?0:RouteUtils.calcDistance(route,1.,1.,scenario.getNetwork()));
            var leg=scenario.getPopulation().getFactory().createLeg("car");
            if (contract!=null) leg.getAttributes().putAttribute(SimZ1TripOd.ATTRIBUTE,contract.tripId);
            leg.setDepartureTime(departure); leg.setTravelTime(estimate.seconds()); leg.setRoute(route);
            return List.of(leg);
        };
    }
}
