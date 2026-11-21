/* *********************************************************************** *
 * project: org.matsim.*
 * QueueNode.java
 *                                                                         *
 * *********************************************************************** *
 *                                                                         *
 * copyright       : (C) 2007 by the members listed in the COPYING,        *
 *                   LICENSE and WARRANTY file.                            *
 * email           : info at matsim dot org                                *
 *                                                                         *
 * *********************************************************************** *
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *   See also COPYING, LICENSE and WARRANTY file                           *
 *                                                                         *
 * *********************************************************************** */

package org.matsim.core.mobsim.qsim.qnetsimengine;

import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.LinkEnterEvent;
import org.matsim.api.core.v01.events.LinkLeaveEvent;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Node;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.config.groups.QSimConfigGroup.NodeTransition;
import org.matsim.core.gbl.Gbl;
import org.matsim.core.gbl.MatsimRandom;
import org.matsim.core.mobsim.framework.MobsimAgent;
import org.matsim.core.mobsim.framework.PassengerAgent;
import org.matsim.core.mobsim.qsim.interfaces.NetsimLink;
import org.matsim.core.mobsim.qsim.qnetsimengine.QNetsimEngineI.NetsimInternalInterface;
import org.matsim.core.mobsim.qsim.qnetsimengine.TurnAcceptanceLogic.AcceptTurn;

import java.util.Arrays;
import java.util.Comparator;
import java.util.Random;
import java.util.ArrayList;
import java.util.List;
import gt.edu.uvg.sim.zona1.PriorityMovements;
import gt.edu.uvg.sim.zona1.SimZ1AdmissionConfigGroup;
import gt.edu.uvg.sim.zona1.Zona1PriorityConfigGroup;

/**
 * Represents a node in the QSimulation.
 */
// Scoped copy of MATSim 15.0 QNodeImpl; no dependency class is replaced.
// Source SHA-256: 3ad926638abb34a8116e660e70ee9eca998eb8fe9001861e2a60f6f36bcf0118
// https://github.com/matsim-org/matsim-libs/blob/15.0/matsim/src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/QNodeImpl.java
// Changes: scoped diagnostics/priority callbacks and opt-in strict receiver admission.
final class Zona1QNodeImpl extends AbstractQNode {
	private static final Logger log = LogManager.getLogger(Zona1QNodeImpl.class);
	public static class Builder {
		private final NetsimInternalInterface netsimEngine;
		private final NetsimEngineContext context;
		private final QSimConfigGroup qsimConfig;
        private final Zona1NativeDiagnostics diagnostics;
		public Builder( NetsimInternalInterface netsimEngine2, NetsimEngineContext context, QSimConfigGroup qsimConfig, Zona1NativeDiagnostics diagnostics ) {
			this.netsimEngine = netsimEngine2;
			this.context = context;
			this.qsimConfig = qsimConfig;
            this.diagnostics = diagnostics;
		}
		private TurnAcceptanceLogic turnAcceptanceLogic = new DefaultTurnAcceptanceLogic() ;
        private gt.edu.uvg.sim.zona1.SimZ1RouteSafety routeSafety;
        private SimZ1AdmissionConfigGroup admission = new SimZ1AdmissionConfigGroup();
        private Zona1PriorityConfigGroup conflictSettings = new Zona1PriorityConfigGroup();
        public void setAdmissionPolicy(SimZ1AdmissionConfigGroup admission, Zona1PriorityConfigGroup conflicts) {
            this.admission = java.util.Objects.requireNonNull(admission);
            this.conflictSettings = java.util.Objects.requireNonNull(conflicts);
        }
        public void setRouteSafety(gt.edu.uvg.sim.zona1.SimZ1RouteSafety routeSafety) {this.routeSafety=routeSafety;}
		public final void setTurnAcceptanceLogic( TurnAcceptanceLogic turnAcceptanceLogic ) {
			this.turnAcceptanceLogic = turnAcceptanceLogic ;
		}
		public Zona1QNodeImpl build( Node n ) {
			return new Zona1QNodeImpl( n, context, netsimEngine, turnAcceptanceLogic, qsimConfig, diagnostics, routeSafety,
                admission.isStrict() ? new PriorityMovements(n, conflictSettings) : null, admission.getWholeVehicleReservation() ) ;
		}
	}

	private final QLinkI[] inLinksArrayCache;
	private final QLinkI[] tempLinks;
	private Double[] inLinkPriorities;

	private final Random random;
	private final NetsimEngineContext context;
	private final NetsimInternalInterface netsimEngine;

	private final TurnAcceptanceLogic turnAcceptanceLogic ;
    private final Zona1NativeDiagnostics diagnostics;
    private final gt.edu.uvg.sim.zona1.SimZ1RouteSafety routeSafety;
    // MATSim 15 assigns one runner per node and its outlinks, then joins every
    // node task before the link phase. Each receiving link has one fromNode.
    // Thus check + insertion + commit below have a single owning actor; there
    // is no global reservation/lock and no downstream-buffer head read.
    private final PriorityMovements admissionConflicts;
    private final boolean wholeVehicleReservation;
    private final List<PriorityMovements.Movement> admitted = new ArrayList<>();
    private record Crossing(PriorityMovements.Movement movement, org.matsim.api.core.v01.Id<org.matsim.vehicles.Vehicle> vehicle,
        String corridor,double clearFront,double notBefore) { }
    private final List<Crossing> crossings=new ArrayList<>();
    private double admissionStep = Double.NEGATIVE_INFINITY;
	private NodeTransition nodeTransitionLogic;
	private boolean stopMoveNodeWhenSingleOutlinkFull;
	private boolean atLeastOneOutgoingLaneIsJammed;

	/**
	 * Checks if capacity is significant positive.
	 * This allows for a small eps unequal to zero to mitigate rounding errors that can happen
	 * with non integer capacities.
	 */
	private static boolean capacityLeft(double x) {
		return x > 1E-10;
	}

	private Zona1QNodeImpl(final Node n, NetsimEngineContext context, NetsimInternalInterface netsimEngine2,
			TurnAcceptanceLogic turnAcceptanceLogic, QSimConfigGroup qsimConfig, Zona1NativeDiagnostics diagnostics,
            gt.edu.uvg.sim.zona1.SimZ1RouteSafety routeSafety, PriorityMovements admissionConflicts, boolean wholeVehicleReservation) {
		super(n) ;
		this.netsimEngine = netsimEngine2 ;
		this.context = context ;
		this.turnAcceptanceLogic = turnAcceptanceLogic;
        this.diagnostics = diagnostics;
        this.routeSafety = routeSafety;
        this.admissionConflicts = admissionConflicts;
        this.wholeVehicleReservation = wholeVehicleReservation;
		this.nodeTransitionLogic = qsimConfig.getNodeTransitionLogic();

		switch (nodeTransitionLogic) {
		case emptyBufferAfterBufferRandomDistribution_nodeBlockedWhenSingleOutlinkFull:
		case moveVehByVehRandomDistribution_nodeBlockedWhenSingleOutlinkFull:
		case moveVehByVehDeterministicPriorities_nodeBlockedWhenSingleOutlinkFull:
			this.stopMoveNodeWhenSingleOutlinkFull = true;
			break;
		case emptyBufferAfterBufferRandomDistribution_dontBlockNode:
		case moveVehByVehRandomDistribution_dontBlockNode:
			this.stopMoveNodeWhenSingleOutlinkFull = false;
			break;
		default:
			throw new UnsupportedOperationException("Node transition logic " + nodeTransitionLogic + " is not implemented.");
		}

		int nofInLinks = n.getInLinks().size();
		this.inLinksArrayCache = new QLinkI[nofInLinks];
		this.tempLinks = new QLinkI[nofInLinks];
		if (this.context.qsimConfig.getNumberOfThreads() > 1) {
			// This could just as well be the "normal" case. The second alternative
			// is just there so some scenarios / test cases stay
			// "event-file-compatible". Consider removing the second alternative.
			this.random = MatsimRandom.getLocalInstance();
		} else {
			this.random = MatsimRandom.getRandom();
		}
	}

	/**
	 * Loads the inLinks-array with the corresponding links.
	 * Cannot be called in constructor, as the queueNetwork does not yet know
	 * the queueLinks. Should be called by QueueNetwork, after creating all
	 * QueueNodes and QueueLinks.
	 */
	@Override
	public void init() {
		int i = 0;
		for (Link l : this.node.getInLinks().values()) {
			QNetwork network = netsimEngine.getNetsimNetwork() ;
			this.inLinksArrayCache[i] = network.getNetsimLinks().get(l.getId());
			i++;
		}
		/* As the order of links has an influence on the simulation results,
		 * the nodes are sorted to avoid indeterministic simulations. dg[april08]
		 */
		Arrays.sort(this.inLinksArrayCache, new Comparator<NetsimLink>() {
			@Override
			public int compare(NetsimLink o1, NetsimLink o2) {
				return o1.getLink().getId().compareTo(o2.getLink().getId());
			}
		});
	}

	/**
	 * Moves vehicles from the inlinks' buffer to the outlinks where possible.<br>
	 * The inLinks are randomly chosen, and for each link all vehicles in the
	 * buffer are moved to their desired outLink as long as there is space. If the
	 * front most vehicle in a buffer cannot move across the node because there is
	 * no free space on its destination link, the work on this inLink is finished
	 * and the next inLink's buffer is handled (this means, that at the node, all
	 * links have only like one lane, and there are no separate lanes for the
	 * different outLinks. Thus if the front most vehicle cannot drive further,
	 * all other vehicles behind must wait, too, even if their links would be
	 * free).
	 *
	 * @param now
	 *          The current time in seconds from midnight.
	 * @return
	 * 		Whether the QNode stays active or not.
	 */
	@Override
	public boolean doSimStep(final double now) {
        if(turnAcceptanceLogic instanceof gt.edu.uvg.sim.zona1.UnsignalizedPriority.StopAndYield priority)
            priority.observeHeads(netsimEngine.getNetsimNetwork(),now);

		if (inLinkPriorities == null) {
			/* initialize inLink priorities.
			 * unfortunately, this can't be done in init() because when capacities are changed
			 * before controler.run() init() uses the old capacities. theresa, may'20 */
			inLinkPriorities = new Double[inLinksArrayCache.length];
			for (int inLinkCounter=0; inLinkCounter<this.inLinksArrayCache.length; inLinkCounter++) {
				double linkCap = this.inLinksArrayCache[inLinkCounter].getLink().getCapacity(now);
				inLinkPriorities[inLinkCounter] = 1. / linkCap;
			}
		}

		// reset congestion flag
		this.atLeastOneOutgoingLaneIsJammed = false;

		double inLinksCapSum = 0.0;
		// Check all incoming links for buffered agents
		for (int inLinkIndex = 0; inLinkIndex < this.inLinksArrayCache.length; inLinkIndex++) {
			QLinkI link = this.inLinksArrayCache[inLinkIndex];
			if (!link.isNotOfferingVehicle()) {
				this.tempLinks[inLinkIndex] = link;
				inLinksCapSum += link.getLink().getCapacity(now);
			}
		}

		if (!capacityLeft(inLinksCapSum)) {
			this.setActive(false);
			return false; // Nothing to do
		}

		// select vehicles to be moved over the node. The order of vehicles selected depends on the chosen node transition logic.
		switch (nodeTransitionLogic) {
		case emptyBufferAfterBufferRandomDistribution_dontBlockNode:
		case emptyBufferAfterBufferRandomDistribution_nodeBlockedWhenSingleOutlinkFull:
			// randomize based on link capacity: select a link; if next links have enough space all vehicles from the buffer are allowed to pass the node
			while (capacityLeft(inLinksCapSum)) {
				double rndNum = random.nextDouble() * inLinksCapSum;
				double selCap = 0.0;
				for (int i = 0; i < this.inLinksArrayCache.length; i++) {
					QLinkI link = this.tempLinks[i];
					if (link != null) {
						// link is offering vehicles
						selCap += link.getLink().getCapacity(now);
						if (selCap >= rndNum) {
							// try to move vehicles from this link over the node
							inLinksCapSum -= link.getLink().getCapacity(now);
							this.tempLinks[i] = null;
							this.moveLink(link, now);
							if (this.stopMoveNodeWhenSingleOutlinkFull && this.atLeastOneOutgoingLaneIsJammed) {
								// consider intersection as blocked; stop this node sim step
								return true;
							}
							break;
						}
					}
				}
			}
			break;
		case moveVehByVehRandomDistribution_dontBlockNode:
		case moveVehByVehRandomDistribution_nodeBlockedWhenSingleOutlinkFull:
			// randomize based on link capacity: select the vehicles (one by one) that are allowed to pass the node
			while (capacityLeft(inLinksCapSum)) {
				double rndNum = random.nextDouble() * inLinksCapSum;
				double selCap = 0.0;
				for (int i = 0; i < this.inLinksArrayCache.length; i++) {
					QLinkI link = this.tempLinks[i];
					if (link != null) {
						// link is offering vehicles
						selCap += link.getLink().getCapacity(now);
						if (selCap >= rndNum) {
							// try to move a vehicle from this link over the node
							if ( ! moveFirstVehicleOnLink(now, link)) {
								// the link is not able to move (more) vehicles in this time step
								inLinksCapSum -= link.getLink().getCapacity(now);
								this.tempLinks[i] = null;
							} else {
								// a vehicle has been moved
							}
							if (this.stopMoveNodeWhenSingleOutlinkFull && this.atLeastOneOutgoingLaneIsJammed) {
								// consider intersection as blocked; stop this node sim step
								return true;
							}
							// select the next link (could be the same again) that is allowed to move a vehicle. I.e. start again with the beginning of the while-loop
							break;
						}
					}
				}
			}
			break;
		case moveVehByVehDeterministicPriorities_nodeBlockedWhenSingleOutlinkFull:
			// deterministically choose the inLinks vehicle by vehicle based on their capacity and also account for decisions made in previous time steps (i.e. update priorities) to approximate the correct distribution over time.
			double prioWithWhichTheLastVehWasSent = 0.;
			while (capacityLeft(inLinksCapSum)) {
				// look for the inLink with minimal priority that has vehicles in the buffer (use first one when equal, because links are sorted by ID)
				double minPrio = Float.MAX_VALUE;
				int prioInLinkIndex = -1;
				for (int i = 0; i < this.inLinksArrayCache.length; i++) {
					if (tempLinks[i] != null &&
							/* compare link priorities with some tolerance (done by comparing the float part of the double).
							 * otherwise, priorities that should be equal are different when compared as double because its fixed precision
							 * (e.g. 1/7200 + 1/7200 as double is greater than 1/3600).
							 * for equal priorities the tie breaking rule is applied (lower link id, see above)
							 */
							(float) this.inLinkPriorities[i].doubleValue() < (float) minPrio) {
						// link is offering vehicles and has lowest priority so far
						minPrio = this.inLinkPriorities[i];
						prioInLinkIndex = i;
					}
				}
				QLinkI selectedLink = this.inLinksArrayCache[prioInLinkIndex];

				// try to move a vehicle from this selected link over the node
				if ( ! moveFirstVehicleOnLink(now, selectedLink)) {
					// the link is not able to move (more) vehicles in this time step
					inLinksCapSum -= selectedLink.getLink().getCapacity(now);
					this.tempLinks[prioInLinkIndex] = null;
				} else {
					// a vehicle has been moved; update priority of the selected link
					prioWithWhichTheLastVehWasSent = minPrio;
					this.inLinkPriorities[prioInLinkIndex] += 1. / selectedLink.getLink().getCapacity(now);
				}
				if (this.atLeastOneOutgoingLaneIsJammed) {
					// stopMoveNodeWhenSingleOutlinkFull is always true for this node transition
					// consider intersection as blocked; stop this node sim step; (*)
					updatePriorities(now, prioWithWhichTheLastVehWasSent, prioInLinkIndex);
					return true;
				}

				// select the next link (could be the same again) that is allowed to move a vehicle. I.e. start again with the beginning of the while-loop
			}
			// vehicle moving done for this time step. update priorities
			updatePriorities(now, prioWithWhichTheLastVehWasSent, -1);
			break;
		default:
			throw new UnsupportedOperationException("Node transition logic " + nodeTransitionLogic + " is not implemented.");
		}

		return true;
	}

	private void updatePriorities(final double now, double prioWithWhichTheLastVehWasSent, int linkIndexToBeExcluded) {

		for (int linkIndex=0; linkIndex < this.inLinkPriorities.length; linkIndex++) {
			// when the node was blocked (see * above) no priority updating is necessary for the blocked links
			if (linkIndex != linkIndexToBeExcluded && tempLinks[linkIndex] == null) {
				// shift priorities of links that where disabled earlier because of other reasons, e.g. because their buffer was empty or a traffic light showed red,
				// to the level of the other priorities such that they are not overprioritized in next time steps
				inLinkPriorities[linkIndex] = prioWithWhichTheLastVehWasSent
						+ 1. / inLinksArrayCache[linkIndex].getLink().getCapacity(now);
			}
			// shift all priorities around zero accordingly to avoid overflow of double at some time step
			inLinkPriorities[linkIndex] -= prioWithWhichTheLastVehWasSent;
		}
	}

	/**
	 * @return <code>true</code> if a vehicle was successfully moved over the node, <code>false</code>
	 * otherwise (e.g. in case all next links are jammed)
	 *
	 * This logic is only implemented for the case without lanes. When multiple lanes exist for a link, an exception is thrown.
	 */
	private boolean moveFirstVehicleOnLink(final double now, QLinkI link) {
		if (link.getOfferingQLanes().size() > 1) {
			throw new RuntimeException("The qsim node transition parameter " + NodeTransition.moveVehByVehRandomDistribution_dontBlockNode + ", "
					+ NodeTransition.moveVehByVehRandomDistribution_nodeBlockedWhenSingleOutlinkFull + " and "
						+ NodeTransition.moveVehByVehDeterministicPriorities_nodeBlockedWhenSingleOutlinkFull
							+ " are only implemented for the case without lanes. But link " + link.getLink().getId()
								+ " in your scenario has more than one lane. "
									+ "Use the default node transiton " + NodeTransition.emptyBufferAfterBufferRandomDistribution_dontBlockNode
										+ " or " + NodeTransition.emptyBufferAfterBufferRandomDistribution_nodeBlockedWhenSingleOutlinkFull
											+ " or adapt the implementation such that it also works for lanes.");
		}
		for (QLaneI lane : link.getOfferingQLanes()) {
			if (! lane.isNotOfferingVehicle()) {
				QVehicle veh = lane.getFirstVehicle();
				if (moveVehicleOverNode(veh, link, lane, now)) {
					// vehicle was moved. stop here
					return true;
				} else {
					// vehicle was not moved, e.g. because the next link is jammed or a traffic light on this link shows red.
					if (this.stopMoveNodeWhenSingleOutlinkFull && this.atLeastOneOutgoingLaneIsJammed) {
						// next link/lane is jammed. stop vehicle moving for the whole node
						return false;
					} else {
						// try next lane
						continue;
					}
				}
			}
		}
		return false;
	}

	private void moveLink(final QLinkI link, final double now){
		if (wholeVehicleReservation && link.getOfferingQLanes().size() > 1) {
            // Body clearance can serialize heads from several native lanes.
            // Draining lanes in their fixed ID order lets a stream of newly
            // exposed heads repeatedly take the only receiving/crossing space
            // ahead of an older head. Arbitrate requests by native head age;
            // every request still runs the unchanged turn/receipt/body checks.
            // A failed head excludes only its own lane for this visit. Refresh
            // age after each successful pop so a follower cannot inherit its
            // predecessor's priority, and preserve FIFO within each lane.
            var candidates = new ArrayList<QLaneI>(link.getOfferingQLanes());
            candidates.removeIf(QLaneI::isNotOfferingVehicle);
            while (!candidates.isEmpty()) {
                QLaneI oldest = candidates.get(0);
                for (var candidate : candidates) {
                    int age = Double.compare(candidate.getLastMovementTimeOfFirstVehicle(), oldest.getLastMovementTimeOfFirstVehicle());
                    if (age < 0 || age == 0 && candidate.getId().toString().compareTo(oldest.getId().toString()) < 0) oldest = candidate;
                }
                if (!moveVehicleOverNode(oldest.getFirstVehicle(), link, oldest, now)) {
                    if (this.stopMoveNodeWhenSingleOutlinkFull && this.atLeastOneOutgoingLaneIsJammed) return;
                    candidates.remove(oldest);
                } else if (oldest.isNotOfferingVehicle()) candidates.remove(oldest);
            }
            return;
		}
		for (QLaneI lane : link.getOfferingQLanes()) {
			while (! lane.isNotOfferingVehicle()) {
				QVehicle veh = lane.getFirstVehicle();
				if (! moveVehicleOverNode(veh, link, lane, now )) {
					// vehicle was not moved, e.g. because the next link is jammed or a traffic light on this link shows red.
					if (this.stopMoveNodeWhenSingleOutlinkFull && this.atLeastOneOutgoingLaneIsJammed) {
						// next link/lane is jammed. stop vehicle moving for the whole node
						return;
					} else {
						// try next lane
						break;
					}
				}
			}
		}
	}



	// ////////////////////////////////////////////////////////////////////
	// Queue related movement code
	// ////////////////////////////////////////////////////////////////////
	/**
	 * @return <code>true</code> if the vehicle was successfully moved over the node, <code>false</code>
	 * otherwise (e.g. in case where the next link is jammed)
	 */
	private boolean moveVehicleOverNode( final QVehicle veh, QLinkI fromLink, final QLaneI fromLane, final double now ) {
		var occupancy=wholeVehicleReservation?SimZ1CorridorOccupancy.get(context.qsimConfig):null;
        if(wholeVehicleReservation&&occupancy==null)throw new IllegalStateException("Missing corridor occupancy ledger");
		if (admissionConflicts != null && !Double.isFinite(now))
            throw new IllegalArgumentException("Non-finite strict admission time at node " + node.getId());
		if (admissionConflicts != null && admissionStep != now) {
            if (now < admissionStep)
                throw new IllegalArgumentException("Non-monotone strict admission time at node " + node.getId());
            admissionStep = now;
            admitted.clear();
        }
		Id<Link> nextLinkId = veh.getDriver().chooseNextLinkId();
		Link currentLink = fromLink.getLink() ;
        if(occupancy!=null&&occupancy.lockedByOther(node.getId(),veh.getId())) {
            diagnostics.storage(currentLink,fromLane,nextLinkId,veh,now,"storage_passage_lock","WAIT");return false;
        }
        boolean passage=occupancy!=null&&occupancy.preauthorized(veh.getId(),currentLink.getId(),nextLinkId);
        if(passage&&fromLane instanceof org.matsim.core.mobsim.qsim.interfaces.SignalizeableItem signal&&!signal.hasGreenForToLink(nextLinkId))
            throw new IllegalStateException("PASSAGE_SIGNAL_WINDOW_BREACH: "+veh.getId()+" at "+currentLink.getId()+" time="+now);
        var passageProof=passage?occupancy.passagePriorityProof(veh.getId(),currentLink.getId(),nextLinkId):java.util.Map.<String,String>of();

        // Native queue routing normally prevents this state; a changed route must
        // also be checked at execution. A forbidden turn cannot be fixed by waiting.
        var nextNativeLink=nextLinkId==null?null:this.netsimEngine.getNetsimNetwork().getNetsimLinks().get(nextLinkId);
        if(nextNativeLink!=null && nextNativeLink.getLink().getFromNode()==currentLink.getToNode() && routeSafety!=null &&
                !routeSafety.laneAllowsVehicle(currentLink.getId(),fromLane.getId(),nextLinkId,veh.getId())) {
            diagnostics.storage(currentLink,fromLane,nextLinkId,veh,now,"turn_restriction","ABORT");
            moveVehicleFromInlinkToAbort(veh,fromLane,now,currentLink.getId());
            return true;
        }

		AcceptTurn turn = passage?(turnAcceptanceLogic instanceof gt.edu.uvg.sim.zona1.UnsignalizedPriority.StopAndYield priority?
            priority.passagePermission(currentLink,fromLane,nextLinkId,veh,now,passageProof):AcceptTurn.GO):turnAcceptanceLogic.isAcceptingTurn(currentLink, fromLane, nextLinkId, veh, this.netsimEngine.getNetsimNetwork(), now);
		diagnostics.turn(currentLink, fromLane, nextLinkId, veh, this.netsimEngine.getNetsimNetwork(), now, turn, turnAcceptanceLogic);
		if ( turn.equals(AcceptTurn.ABORT) ) {
			moveVehicleFromInlinkToAbort( veh, fromLane, now, currentLink.getId() ) ;
			return true ;
		} else if ( turn.equals(AcceptTurn.WAIT) ) {
			return false;
		}

        var movement = new PriorityMovements.Movement(currentLink.getId(), nextLinkId);
        if(occupancy!=null&&!passage) {
            crossings.removeIf(c->occupancy.crossingCleared(c.vehicle(),c.corridor(),c.clearFront(),c.notBefore(),now));
            for(var prior:crossings)if(movement.equals(prior.movement())||admissionConflicts.conflicts(movement,prior.movement())) {
                diagnostics.admissionConflict(currentLink,fromLane,nextLinkId,veh,now,prior.movement(),"modeled_body_clearance");
                return false;
            }
        }
        if (admissionConflicts != null&&!passage) {
            // Applies also to signalized nodes with intersectionLogic=NONE.
            // Green/GO is permission to request entry, not a committed crossing.
            for (var prior : admitted) if (admissionConflicts.conflicts(movement, prior)) {
                diagnostics.admissionConflict(currentLink, fromLane, nextLinkId, veh, now,
                    prior, admissionConflicts.evidence(movement, prior));
                return false;
            }
        }

		QLinkI nextQueueLink = this.netsimEngine.getNetsimNetwork().getNetsimLinks().get(nextLinkId);
		QLaneI nextQueueLane = nextQueueLink.getAcceptingQLane() ;
		final boolean nativeReceiverAccepted = nextQueueLane.isAcceptingFromUpstream();
		if (nativeReceiverAccepted && (occupancy==null ||
                occupancy.canEnter(veh,nextLinkId,nextQueueLane.getId().toString(),now))) {
			moveVehicleFromInlinkToOutlink(veh, currentLink.getId(), fromLane, nextLinkId, nextQueueLane);
            if(occupancy!=null && !passage && !java.util.Objects.equals(occupancy.corridorId(currentLink.getId()),occupancy.corridorId(nextLinkId))) {
                double distance=occupancy.entryClearanceDistance(veh,nextLinkId);
                double velocity=Math.min(veh.getVehicle().getType().getMaximumVelocity(),Math.min(currentLink.getFreespeed(now),nextQueueLink.getLink().getFreespeed(now)));
                if(!(velocity>0)||!Double.isFinite(velocity))throw new IllegalStateException("Invalid crossing clearance speed");
                crossings.add(new Crossing(movement,veh.getId(),occupancy.corridorId(nextLinkId),occupancy.offset(nextLinkId)+distance,now+distance/velocity));
            }
            if (admissionConflicts != null) {
                admitted.add(movement);
                diagnostics.admitted(currentLink, fromLane, nextLinkId, veh, now, nextQueueLane);
            }
            if(turnAcceptanceLogic instanceof gt.edu.uvg.sim.zona1.UnsignalizedPriority.StopAndYield priority) {
                if(passage)priority.crossedPassage(currentLink,fromLane,nextLinkId,veh,netsimEngine.getNetsimNetwork(),now,passageProof);
                else priority.crossed(currentLink,fromLane,nextLinkId,veh,netsimEngine.getNetsimNetwork(),now,false);
            }
			return true;
		}
		// else, i.e. next link or lane is jammed
		if(occupancy!=null)occupancy.passageStorageWait(veh,currentLink.getId(),fromLane.getId().toString(),nextLinkId,nextQueueLane,now);
		this.atLeastOneOutgoingLaneIsJammed = true;

		if (admissionConflicts == null && vehicleIsStuck(fromLane, now)) {
			/* We just push the vehicle further after stucktime is over, regardless
			 * of if there is space on the next link or not.. optionally we let them
			 * die here, we have a config setting for that!
			 */
			if (this.context.qsimConfig.isRemoveStuckVehicles()) {
                diagnostics.storage(currentLink, fromLane, nextLinkId, veh, now, "storage_stuck_removal", "ABORT", nextQueueLink, nextQueueLane, nativeReceiverAccepted);
				moveVehicleFromInlinkToAbort(veh, fromLane, now, currentLink.getId());
				return false ;
			} else {
                diagnostics.storage(currentLink, fromLane, nextLinkId, veh, now, "storage_forced_move", "FORCE", nextQueueLink, nextQueueLane, nativeReceiverAccepted);
				moveVehicleFromInlinkToOutlink(veh, currentLink.getId(), fromLane, nextLinkId, nextQueueLane);
                if(turnAcceptanceLogic instanceof gt.edu.uvg.sim.zona1.UnsignalizedPriority.StopAndYield priority)
                    priority.crossed(currentLink,fromLane,nextLinkId,veh,netsimEngine.getNetsimNetwork(),now,true);
				return true;
				// (yyyy why is this returning `true'?  Since this is a fix to avoid gridlock, this should proceed in small steps.
				// kai, feb'12)
			}
		}

        // Strict admission never turns a rejected receiver into FORCE/ABORT.
        // Preserve the source queue even beyond stuckTime (also defensively if
        // removeStuckVehicles was enabled). Gridlock may persist; this does not
        // promise eventual movement or silently change native storage capacity.
		diagnostics.storage(currentLink, fromLane, nextLinkId, veh, now, "storage_wait", "WAIT", nextQueueLink, nextQueueLane, nativeReceiverAccepted);
        if(turnAcceptanceLogic instanceof gt.edu.uvg.sim.zona1.UnsignalizedPriority.StopAndYield priority)
            priority.storageWait(currentLink,fromLane,nextLinkId,veh,now);
		return false;

	}

    double passageStopSeconds(Link from){return turnAcceptanceLogic instanceof gt.edu.uvg.sim.zona1.UnsignalizedPriority.StopAndYield priority?priority.passageStopSeconds(from):0;}
    double passageTraversalUpperBound(QVehicle vehicle,Link from,int modelSlot,double now,String activityBufferQueue){
        var qlink=netsimEngine.getNetsimNetwork().getNetsimLinks().get(from.getId());double bound=0;
        if(activityBufferQueue!=null&&!qlink.getAcceptingQLane().getId().toString().equals(activityBufferQueue))
            throw new IllegalStateException("Activity passage must name its actual accepting queue");
        if(qlink instanceof QLinkLanesImpl multi){
            for(var lane:multi.getQueueLanes().values())if(lane.getId().toString().endsWith(".original")||lane.getId().toString().endsWith(".lane."+modelSlot)){
                if(!(lane instanceof QueueWithBuffer queue))throw new IllegalStateException("Unsupported passage queue implementation");
                bound+=queue.emptyTraversalUpperBound(vehicle,now,lane.getId().toString().equals(activityBufferQueue));
            }
        }else if(qlink.getAcceptingQLane() instanceof QueueWithBuffer queue)bound=queue.emptyTraversalUpperBound(vehicle,now,queue.getId().toString().equals(activityBufferQueue));
        else throw new IllegalStateException("Unsupported passage queue implementation");
        return bound;
    }
    double passageGreenRemaining(Link from,Link to,int modelSlot,double now){
        var qlink=netsimEngine.getNetsimNetwork().getNetsimLinks().get(from.getId());
        for(var lane:qlink.getOfferingQLanes())if(qlink.getOfferingQLanes().size()==1||lane.getId().toString().endsWith(".lane."+modelSlot))
            return SimZ1CorridorOccupancy.get(context.qsimConfig).greenRemaining(from.getId(),lane.getId(),to.getId(),now);
        throw new IllegalStateException("Missing passage terminal slot");
    }
    boolean receiptQueueReady(Link link,int modelSlot,boolean needsTerminal){
        var qlink=netsimEngine.getNetsimNetwork().getNetsimLinks().get(link.getId());
        if(qlink==null||!qlink.getAcceptingQLane().isAcceptingFromUpstream())return false;
        if(!needsTerminal)return true;
        for(var lane:qlink.getOfferingQLanes())if(qlink.getOfferingQLanes().size()==1||lane.getId().toString().endsWith(".lane."+modelSlot))return lane.isAcceptingFromUpstream();
        return false;
    }
    boolean passageClear(QVehicle vehicle,Link from,Link to,int modelSlot,double now) {
        lastPassageCheck=checkPassage(vehicle,from,to,modelSlot,now);
        return lastPassageCheck.reason().equals("passage_priority_clear");
    }
    record PassageCheck(String reason,List<QVehicle> blockers) { }
    private PassageCheck lastPassageCheck=new PassageCheck("not_queried",List.of());
    PassageCheck lastPassageCheck(){return lastPassageCheck;}
    QLaneI passageHead(QVehicle vehicle,Link from,String queue,double now){
        var qnet=netsimEngine.getNetsimNetwork();var qlink=qnet.getNetsimLinks().get(from.getId());
        if(qlink==null)return null;
        for(var lane:qlink.getOfferingQLanes())if(lane.getId().toString().equals(queue)&&!lane.isNotOfferingVehicle()&&lane.getFirstVehicle()==vehicle){
            if(turnAcceptanceLogic instanceof gt.edu.uvg.sim.zona1.UnsignalizedPriority.StopAndYield priority&&
                    !priority.passageHeadReady(from,lane,vehicle,qnet,now))return null;
            return lane;
        }
        return null;
    }
    private PassageCheck passageBlocked(String reason){return new PassageCheck(reason,List.of());}
    private PassageCheck checkPassage(QVehicle vehicle,Link from,Link to,int modelSlot,double now) {
        var occupancy=SimZ1CorridorOccupancy.get(context.qsimConfig);
        crossings.removeIf(c->occupancy.crossingCleared(c.vehicle(),c.corridor(),c.clearFront(),c.notBefore(),now));
        var movement=new PriorityMovements.Movement(from.getId(),to.getId());
        for(var c:crossings)if(movement.equals(c.movement())||admissionConflicts.conflicts(movement,c.movement()))return passageBlocked("crossing_body_not_clear");
        if(admissionStep==now)for(var prior:admitted)if(movement.equals(prior)||admissionConflicts.conflicts(movement,prior))return passageBlocked("crossing_admitted_this_step");
        var qnet=netsimEngine.getNetsimNetwork();var qfrom=qnet.getNetsimLinks().get(from.getId());var qto=qnet.getNetsimLinks().get(to.getId());
        if(qfrom==null||qto==null||!qto.getAcceptingQLane().isAcceptingFromUpstream())return passageBlocked("native_receiver_unavailable");
        QLaneI selected=null;for(var lane:qfrom.getOfferingQLanes())if(qfrom.getOfferingQLanes().size()==1||lane.getId().toString().endsWith(".lane."+modelSlot)){selected=lane;break;}
        if(selected==null)return passageBlocked("native_lane_missing");
        if(routeSafety!=null&&!routeSafety.laneAllowsVehicle(from.getId(),selected.getId(),to.getId(),vehicle.getId()))return passageBlocked("turn_restriction");
        if(selected instanceof org.matsim.core.mobsim.qsim.interfaces.SignalizeableItem signal&&!signal.hasGreenForToLink(to.getId()))return passageBlocked("signal_not_green");
        if(turnAcceptanceLogic instanceof gt.edu.uvg.sim.zona1.UnsignalizedPriority.StopAndYield priority){
            priority.passageMayProceed(from,to.getId(),vehicle,qnet,now);
            var result=priority.getLastPassageDecision();return new PassageCheck(result.reason(),result.blockers());
        }
        return passageBlocked("passage_priority_clear");
    }

	private static int wrnCnt = 0 ;
	private void moveVehicleFromInlinkToAbort(final QVehicle veh, final QLaneI fromLane, final double now, Id<Link> currentLinkId) {
		fromLane.popFirstVehicle();
        var occupancy=SimZ1CorridorOccupancy.get(context.qsimConfig);
        if(occupancy!=null)occupancy.release(veh.getId(),now,"abort");
		// -->
		this.context.getEventsManager().processEvent(new LinkLeaveEvent(now, veh.getId(), currentLinkId));
		// <--

		// first treat the passengers:
		for ( PassengerAgent pp : veh.getPassengers() ) {
			if ( pp instanceof MobsimAgent ) {
				((MobsimAgent)pp).setStateToAbort(now);
				netsimEngine.arrangeNextAgentState((MobsimAgent)pp) ;
			} else if ( wrnCnt < 1 ) {
				wrnCnt++ ;
				log.warn("encountering PassengerAgent that cannot be cast into a MobsimAgent; cannot say if this is a problem" ) ;
				log.warn(Gbl.ONLYONCE) ;
			}
		}

		// now treat the driver:
		veh.getDriver().setStateToAbort(now) ;
		netsimEngine.arrangeNextAgentState(veh.getDriver()) ;

	}

	private void moveVehicleFromInlinkToOutlink(final QVehicle veh, Id<Link> currentLinkId, final QLaneI fromLane, Id<Link> nextLinkId, QLaneI nextQueueLane) {
		double now = this.context.getSimTimer().getTimeOfDay() ;

		fromLane.popFirstVehicle();
		// -->
		//		network.simEngine.getMobsim().getEventsManager().processEvent(new LaneLeaveEvent(now, veh.getId(), currentLinkId, fromLane.getId()));
		this.context.getEventsManager().processEvent(new LinkLeaveEvent(now, veh.getId(), currentLinkId));
		// <--

		veh.getDriver().notifyMoveOverNode( nextLinkId );

		// -->
		this.context.getEventsManager().processEvent(new LinkEnterEvent(now, veh.getId(), nextLinkId));
		// <--
		nextQueueLane.addFromUpstream(veh);
	}

	private boolean vehicleIsStuck(final QLaneI fromLaneBuffer, final double now) {
		//		final double stuckTime = network.simEngine.getStuckTime();
		final double stuckTime = this.context.qsimConfig.getStuckTime() ;
		return (now - fromLaneBuffer.getLastMovementTimeOfFirstVehicle()) > stuckTime;
	}


}
