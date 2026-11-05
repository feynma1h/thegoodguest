# 0341 — a room of twins shows only the twins

**Date:** 2026-11-05
**Status:** Decided

## Context

Boxed objects get models; unboxed objects do not appear; no scanned splats once
twins exist (phase 2 product decisions). The room page read the finish and twins
after the room was already up.

## What we chose

`RoomStage` reads `finish.json` and `furniture.json` before it draws, each request
bounded to 10 s (`EXTRAS_TIMEOUT_MS`); an error or timeout counts as an absent
file. When twins are drawn it hands the viewer no scanned splats, no outlines and
no rearrangement proposal, and the guest's words and counts use the twin count.
Without twins everything is as before.

## Why

Reading first means a scan's objects never show and then swap. The bound keeps a
hung file from holding the room.

## What would change this decision

Twins are drawn only with a finish that fits (a finish failure with twins present
draws the plain room, scanned objects included). If the pipeline ever publishes
twins without a finish, this should be revisited.
