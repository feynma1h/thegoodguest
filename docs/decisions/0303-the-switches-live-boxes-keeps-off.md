# 0303 — two things live boxes keeps in the code and leaves off

**Date:** 2026-11-05
**Status:** Decided

## Context

Live boxes carries two capabilities its current product decisions do not use: Depth Anything v3
as a depth model, and the comparison of the detector's boxes with RoomPlan's. Both were built
and measured. Neither is wanted now.

## What we chose

Keep each, behind one named constant and a test that pins the default:

- **`DepthPolicy.allowsDepthAnything3 = false`.** A phone without LiDAR runs Depth Anything v2
  Small. v3's export — metric depth plus a per-pixel confidence of its own — is still read and
  fitted (`DepthModel`, `DepthAlignment`); only the choice of it is off. Reason: on the operator's
  depth walks v2 beat v3.
- **`RoomPlanClasses.boxedByRoomPlan = false`.** RoomPlan's boxes are not used for what the
  person boxes (0301), so the detector lifts RoomPlan's own categories itself and `RoomPlanMatch`
  compares nothing. With the constant on, those categories are left to RoomPlan
  (`MissReason.leftToRoomPlan`) and the log records each box's agreement with RoomPlan's and any
  it duplicates. Nothing in the app feeds RoomPlan's boxes to the session today.

## Why

Removing them is a decision that is easy to make later and hard to undo: the measurements that
justify the fit and the comparison live in the code and its tests. A constant and a pinned
default cost nothing and say what is off.

## What would change this decision

- **A v3 trial** is one constant. If it wins on a phone without LiDAR, the default changes and
  this note is Spent.
- **RoomPlan's boxes becoming wanted** (to compare the detector with, or to use for its own
  categories) means feeding them to `LiveBoxesSession.acceptRoomPlan` and flipping the constant.
