"""
Counting module for the pig counting application.

This module handles the counting logic based on object crossing a vertical line.
"""

import numpy as np
import logging

logger = logging.getLogger(__name__)


class Counting:
    """
    Counting class to manage object counting logic.
    
    Attributes:
        detections (dict): Dictionary to store detection history.
        trails (dict): Dictionary to store tracking trails.
        area_in_list (list): List to store track IDs in the "in" area.
        area_out_list (list): List to store track IDs in the "out" area.
    """
    
    def __init__(self, shared_state=None, pig_confidence_threshold=0.7, offset_counting_line=0,
                 lost_buffer_frames=60, reassoc_line_band=200,
                 reassoc_max_dist_x=120, reassoc_max_dist_y=80,
                 hysteresis_px=25, mirror_guard="log",
                 mirror_max_age=15, mirror_line_band=100,
                 mirror_new_band=120, mirror_max_dist_y=60,
                 resurrection_threshold=5, resurrection_min_jump=150,
                 guard_max_age=15, reid_window=15, reid_min_age=3):
        """Initialize the counting object."""
        self.detections = {}
        self.trails = shared_state.trails if shared_state else {}
        self.area_in_list = []
        self.area_out_list = []
        self.shared_state = shared_state
        self.pig_confidence_threshold = pig_confidence_threshold
        self.offset_counting_line=offset_counting_line
        # ID-switch recovery guard state
        self.lost_tracks = {}            # {track_id: {"cx","cy","side","frame"}}
        self.frame_counter = 0
        self.prev_visible_ids = set()    # IDs visible last frame (to detect new losses)
        self.lost_buffer_frames = lost_buffer_frames
        self.reassoc_line_band = reassoc_line_band
        self.reassoc_max_dist_x = reassoc_max_dist_x
        self.reassoc_max_dist_y = reassoc_max_dist_y
        # Hysteresis: a crossing is only counted when the centroid passes the
        # line by H pixels, to absorb bbox jitter right at the line.
        self.hysteresis_px = hysteresis_px
        # Mirror guard: a new ID appearing on the RIGHT while a recently-lost
        # track exists on the LEFT near the line is likely a re-ID of an
        # already-counted pig. Modes: "off" (disabled), "log" (detect & log only,
        # no count change), "enforce" (suppress the upcoming crossed LEFT).
        self.mirror_guard = mirror_guard
        self.mirror_max_age = mirror_max_age
        self.mirror_line_band = mirror_line_band
        self.mirror_new_band = mirror_new_band
        self.mirror_max_dist_y = mirror_max_dist_y
        # Resurrection: track the last frame each ID was actually seen, so we
        # can detect a known ID reappearing after a long absence (re-ID) and
        # avoid firing a crossing on the resulting position jump (Pattern B).
        self.last_seen = {}             # {track_id: frame_counter of last frame seen}
        self.resurrection_threshold = resurrection_threshold
        # Resurrection: min horizontal position jump (px) for a reappeared ID to
        # be considered a re-ID rather than a continuous track (Pattern B).
        self.resurrection_min_jump = resurrection_min_jump
        # Guard max age: max age (frames) of a lost "in" ELIGIBLE for the
        # ID-switch guard fusion. Distinct from lost_buffer_frames (global
        # expiration of lost_tracks): keeping it short avoids fusing with stale
        # lost "in" tracks belonging to other pigs.
        self.guard_max_age = guard_max_age
        # REID-SUPPRESS: detect a known ID (in area_in, not yet counted) that
        # reappears on the LEFT after an absence, while another ID that APPEARED
        # during its absence has recently crossed LEFT. That other ID is almost
        # certainly the re-ID of the same pig (already counted), so we suppress
        # the +1 this ID's position jump would fire. Distinguishes a re-ID from
        # a legitimate occluded crossing (no other ID appeared during the
        # absence -> normal crossing).
        self.reid_window = reid_window      # max age (frames) of a crossing to be "recent"
        self.reid_min_age = reid_min_age    # min absence (frames) to be suspicious
        self.recent_crossings = []          # [{frame, tid, direction}]
        self.first_seen = {}                # {track_id: frame of first appearance}
        self.suppress_count = set()     # track_ids whose next crossed LEFT is suppressed
    
    def count(self, image_raw, result_boxes, result_trackid, result_classid, result_scores=None, counting_class=0, counter_to_right=0):
        """
        Count objects crossing a vertical line.
        
        Args:
            image_raw (numpy.ndarray): Original image.
            result_boxes (numpy.ndarray): Detected bounding boxes.
            result_trackid (numpy.ndarray): Track IDs.
            result_classid (numpy.ndarray): Class IDs.
            result_scores (numpy.ndarray, optional): Detection scores. Defaults to None.
            counting_class (int, optional): Class ID to count. Defaults to 0.
            counter_to_right (int, optional): Current count of objects to the right. Defaults to 0.
            
        Returns:
            int: Updated count of objects moving to the right.
        """
        img_height, img_width = image_raw.shape[:2]
        x = int((img_width / 2) + (img_width * self.offset_counting_line / 100))
        # Hysteresis dead-band: crossings only fire past x±H to absorb jitter.
        x_low = x - self.hysteresis_px
        x_high = x + self.hysteresis_px

        # ------------------------------------------------------------------
        # ID-switch recovery guard: detect tracks lost since last frame and
        # remember their last position + side relative to the counting line.
        # An ID is logged/recorded only ONCE, at the visible->absent transition
        # (not every frame it stays absent), so logs stay readable and the
        # lost_tracks entry keeps its disappearance frame (ages out correctly).
        # ------------------------------------------------------------------
        current_ids = set()
        if len(result_boxes) > 0:
            current_ids = {int(tid) for tid in result_trackid}

        newly_lost = self.prev_visible_ids - current_ids
        for tid in newly_lost:
            last = self.detections.get(tid)
            if last is None:
                continue
            cx, cy = last[2], last[3]
            if tid in self.area_in_list:
                side = "in"     # was on the right side (>
            elif tid in self.area_out_list:
                side = "out"    # was on the left side (<=
            else:
                continue
            self.lost_tracks[tid] = {
                "cx": float(cx), "cy": float(cy),
                "side": side, "frame": self.frame_counter,
            }
            logger.info(
                f"[COUNT] track lost: ID={tid} side={side} "
                f"pos=({cx:.0f},{cy:.0f})"
            )
        self.prev_visible_ids = current_ids

        # Expire stale lost tracks
        for lost_id in [
            lid for lid, d in self.lost_tracks.items()
            if self.frame_counter - d["frame"] > self.lost_buffer_frames
        ]:
            del self.lost_tracks[lost_id]

        self.frame_counter += 1

        # Expire stale recent_crossings (keep only those within reid_window)
        self.recent_crossings = [
            rc for rc in self.recent_crossings
            if self.frame_counter - rc["frame"] <= self.reid_window
        ]

        if len(result_boxes) > 0:
            center_x = (result_boxes[:, 0] + result_boxes[:, 2]) / 2
            center_y = (result_boxes[:, 1] + result_boxes[:, 3]) / 2
            current_status = np.column_stack((center_x, center_y, result_trackid, result_classid))
            
            # Add scores to current_status if provided
            if result_scores is not None:
                current_status = np.column_stack((current_status, result_scores))

            for element in current_status:
                track_id = element[2]
                class_id = element[3]
                
                if track_id in self.detections:
                    last_x, last_y = self.detections[track_id][2], self.detections[track_id][3]
                    self.detections[track_id] = [last_x, last_y, element[0], element[1], self.detections[track_id][4]]

                    # Fix #11: consume the lost_tracks entry of an ID that
                    # reappears, so the ID-switch guard cannot later reuse this
                    # stale "lost in" to fuse a brand-new left-side ID with it
                    # (the pig may have already crossed under this same ID, which
                    # would cause a false +1 - the #11 double-count).
                    if track_id in self.lost_tracks:
                        del self.lost_tracks[track_id]

                    # ----------------------------------------------------------
                    # Resurrection guard (Pattern B): an already-known ID that was
                    # absent for a long time and reappears far from its last
                    # position is a re-ID / erroneous re-association (OC-SORT
                    # re-attached a detection to a stale track). The position
                    # jump (e.g. right->left) would fire a false crossed LEFT
                    # and double-count the pig. Instead, reset its area list by
                    # the CURRENT position with no count change and drop it from
                    # lost_tracks (it is back).
                    # ----------------------------------------------------------
                    _age = self.frame_counter - self.last_seen.get(track_id, self.frame_counter - 1)
                    _jump = abs(element[0] - last_x)
                    if (_jump > self.resurrection_min_jump and _age > self.resurrection_threshold) and (class_id == counting_class):
                        logger.warning(
                            f"[COUNT] RESURRECTION: ID={track_id} reappeared after "
                            f"{_age} frames, jump={_jump:.0f}px; reset area (no crossing) "
                            f"pos=({element[0]:.0f},{element[1]:.0f}) "
                            f"count={counter_to_right}"
                        )
                        if track_id in self.area_in_list:
                            self.area_in_list.remove(track_id)
                        if track_id in self.area_out_list:
                            self.area_out_list.remove(track_id)
                        if element[0] > x:
                            self.area_in_list.append(track_id)
                        else:
                            self.area_out_list.append(track_id)
                        if track_id in self.lost_tracks:
                            del self.lost_tracks[track_id]
                        continue

                    # ----------------------------------------------------------
                    # REID-SUPPRESS: a known ID that was in area_in (right, not yet
                    # counted) reappears on the LEFT (<=x_low) after an absence
                    # (age >= reid_min_age). If another ID that APPEARED during
                    # this ID's absence has recently crossed LEFT, that other ID is
                    # almost certainly the re-ID of the same pig (already counted)
                    # - suppress this ID's +1 to avoid the double-count (the #35
                    # case: ID=10 lost, ID=15 appeared+crossed, ID=10 reappears on
                    # left and would cross again). A legitimate occluded crossing
                    # has NO other ID appearing during the absence, so it is
                    # left to fire normally.
                    # ----------------------------------------------------------
                    if (track_id in self.area_in_list
                            and element[0] <= x_low
                            and _age >= self.reid_min_age
                            and class_id == counting_class):
                        _supp_tid = None
                        for rc in self.recent_crossings:
                            if rc["tid"] == track_id:
                                continue
                            if rc["direction"] != "LEFT":
                                continue
                            if self.frame_counter - rc["frame"] > self.reid_window:
                                continue
                            # the other ID must have first appeared DURING this
                            # ID's absence (i.e. after its last sighting)
                            if self.first_seen.get(rc["tid"], self.frame_counter) > \
                                    self.last_seen.get(track_id, self.frame_counter):
                                _supp_tid = rc["tid"]
                                break
                        if _supp_tid is not None:
                            logger.warning(
                                f"[COUNT] REID-SUPPRESS: ID={track_id} reappeared on "
                                f"left (age={_age}, jump={_jump:.0f}px); ID={_supp_tid} "
                                f"crossed LEFT during its absence -> suppress (+0) "
                                f"count={counter_to_right}"
                            )
                            self.area_in_list.remove(track_id)
                            if track_id not in self.area_out_list:
                                self.area_out_list.append(track_id)
                            if track_id in self.lost_tracks:
                                del self.lost_tracks[track_id]
                            continue

                    # ----------------------------------------------------------
                    # REID-SUPPRESS (mirror, -1): a known ID that was in
                    # area_out (left, already counted +1) reappears on the RIGHT
                    # (>=x_high) after an absence (age >= reid_min_age). If
                    # another ID that APPEARED during this ID's absence has
                    # recently crossed RIGHT, that other ID is almost certainly
                    # the re-ID of the same pig coming back (already
                    # "de-counted" by the other ID's -1) - suppress this ID's
                    # -1 to avoid the double -1. Mirror of the +1 REID-SUPPRESS
                    # above, for the left->right return direction.
                    # ----------------------------------------------------------
                    if (track_id in self.area_out_list
                            and element[0] >= x_high
                            and _age >= self.reid_min_age
                            and class_id == counting_class):
                        _supp_tid = None
                        for rc in self.recent_crossings:
                            if rc["tid"] == track_id:
                                continue
                            if rc["direction"] != "RIGHT":
                                continue
                            if self.frame_counter - rc["frame"] > self.reid_window:
                                continue
                            if self.first_seen.get(rc["tid"], self.frame_counter) > \
                                    self.last_seen.get(track_id, self.frame_counter):
                                _supp_tid = rc["tid"]
                                break
                        if _supp_tid is not None:
                            logger.warning(
                                f"[COUNT] REID-SUPPRESS (RIGHT): ID={track_id} "
                                f"reappeared on right (age={_age}, "
                                f"jump={_jump:.0f}px); ID={_supp_tid} crossed "
                                f"RIGHT during its absence -> suppress (+0) "
                                f"count={counter_to_right}"
                            )
                            self.area_out_list.remove(track_id)
                            if track_id not in self.area_in_list:
                                self.area_in_list.append(track_id)
                            if track_id in self.lost_tracks:
                                del self.lost_tracks[track_id]
                            continue

                    if self.detections[track_id][2] >= x_high and track_id in self.area_out_list:
                        counter_to_right -= 1
                        logger.info(f"[TRACK] ID={track_id} crossed RIGHT // Count {counter_to_right}")
                        self.recent_crossings.append({"frame": self.frame_counter, "tid": track_id, "direction": "RIGHT"})
                        if track_id not in self.area_in_list:
                            self.area_out_list.remove(track_id)
                            self.area_in_list.append(track_id)
                    elif self.detections[track_id][2] <= x_low and track_id in self.area_in_list:
                        if track_id in self.suppress_count:
                            # Mirror guard: this new ID on the right was deemed a
                            # re-ID of an already-counted pig. Suppress the +1.
                            self.suppress_count.discard(track_id)
                            logger.warning(
                                f"[COUNT] MIRROR suppress: ID={track_id} crossing "
                                f"LEFT suppressed (already counted) "
                                f"count={counter_to_right}"
                            )
                        else:
                            counter_to_right += 1
                            logger.info(f"[TRACK] ID={track_id} crossed LEFT // Count {counter_to_right}")
                            self.recent_crossings.append({"frame": self.frame_counter, "tid": track_id, "direction": "LEFT"})
                        if track_id not in self.area_out_list:
                            self.area_in_list.remove(track_id)
                            self.area_out_list.append(track_id)
                else:
                    last_x, last_y = None, None
                    self.detections[track_id] = [last_x, last_y, element[0], element[1], element[3]]

                    # ----------------------------------------------------------
                    # ID-switch recovery guard (BIDIRECTIONNEL)
                    # ----------------------------------------------------------
                    # A brand-new ID appearing already past the line is suspicious:
                    # it is usually a re-detection that got a new ID after an
                    # occlusion at the line. If a track was recently lost on the
                    # OTHER side, close to the line and spatially near, fuse them
                    # and trigger the crossing the switch would have swallowed:
                    #   - new ID on the LEFT (<=x) + lost "in" (right)  -> crossed LEFT  (+1)
                    #   - new ID on the RIGHT (>x) + lost "out" (left)  -> crossed RIGHT (-1)
                    # (the -1 branch handles a pig that already crossed (+1), came
                    # back left->right and got an ID-switch at the line on its
                    # return: without it, the -1 of the return would be lost.)
                    fused = False
                    if element[3] == counting_class:
                        want_side = "in" if element[0] <= x else "out"
                        for lost_id, data in list(self.lost_tracks.items()):
                            # Guard eligibility age: use GUARD_MAX_AGE (short), not
                            # the global LOST_BUFFER_FRAMES. A stale lost track
                            # belonging to a different pig (or to a pig that
                            # already crossed under another ID) must NOT be fused
                            # with this brand-new ID (false crossing on #30/#11).
                            if self.frame_counter - 1 - data["frame"] > self.guard_max_age:
                                continue
                            if data["side"] != want_side:
                                continue
                            if abs(data["cx"] - x) > self.reassoc_line_band:
                                continue
                            dx = abs(element[0] - data["cx"])
                            dy = abs(element[1] - data["cy"])
                            if dx <= self.reassoc_max_dist_x and dy <= self.reassoc_max_dist_y:
                                if element[0] <= x:
                                    # crossed LEFT (+1): pig went right->left
                                    counter_to_right += 1
                                    direction = "LEFT"
                                    target_list = self.area_out_list
                                    other_list = self.area_in_list
                                    logger.warning(
                                        f"[COUNT] ID-SWITCH recovery (LEFT): new "
                                        f"ID={track_id} fused with lost ID={lost_id} "
                                        f"(+1) count={counter_to_right}"
                                    )
                                else:
                                    # crossed RIGHT (-1): pig came back left->right
                                    counter_to_right -= 1
                                    direction = "RIGHT"
                                    target_list = self.area_in_list
                                    other_list = self.area_out_list
                                    logger.warning(
                                        f"[COUNT] ID-SWITCH recovery (RIGHT): new "
                                        f"ID={track_id} fused with lost ID={lost_id} "
                                        f"(-1) count={counter_to_right}"
                                    )
                                # Record this guard-triggered crossing so the
                                # mirrored REID-SUPPRESS can detect a later re-ID of
                                # the same pig reappearing on the same side.
                                self.recent_crossings.append({"frame": self.frame_counter, "tid": track_id, "direction": direction})
                                # The new ID appeared already past the line; the
                                # guard has just triggered the crossing, so the ID
                                # must be marked as already on the destination side
                                # (target_list). Putting it on the source side would
                                # let the next frame fire a spurious crossing and
                                # double-count the pig.
                                if track_id not in target_list:
                                    if track_id in other_list:
                                        other_list.remove(track_id)
                                    target_list.append(track_id)
                                del self.lost_tracks[lost_id]
                                fused = True
                                break

                    if not fused:
                        if element[3] == counting_class and track_id not in self.area_in_list and element[0] > x:
                            self.area_in_list.append(track_id)
                            # --------------------------------------------------
                            # Mirror guard: new ID on the RIGHT + a track recently
                            # lost on the LEFT near the line. This is the mirror of
                            # the ID-switch bug: a pig crossed (+1), was lost on the
                            # left, and got a new ID on the right that will cross
                            # again (+1 = over-count). Modes:
                            #   off     -> disabled
                            #   log     -> detect & log only (default, safe)
                            #   enforce -> suppress the upcoming crossed LEFT of
                            #              this new ID (avoid double count)
                            # --------------------------------------------------
                            if self.mirror_guard != "off":
                                for lost_id, data in list(self.lost_tracks.items()):
                                    if self.frame_counter - 1 - data["frame"] > self.mirror_max_age:
                                        continue
                                    if data["side"] != "out":
                                        continue
                                    if abs(data["cx"] - x) > self.mirror_line_band:
                                        continue
                                    if abs(element[0] - x) > self.mirror_new_band:
                                        continue
                                    if abs(element[1] - data["cy"]) > self.mirror_max_dist_y:
                                        continue
                                    if self.mirror_guard == "enforce":
                                        self.suppress_count.add(track_id)
                                        logger.warning(
                                            f"[COUNT] MIRROR guard: new ID={track_id} "
                                            f"on right fused with lost ID={lost_id} "
                                            f"(suppress future +1)"
                                        )
                                        del self.lost_tracks[lost_id]
                                    else:  # log mode: observe only, do not change state
                                        logger.info(
                                            f"[COUNT] MIRROR candidate: new ID={track_id} "
                                            f"on right, lost ID={lost_id} on left "
                                            f"(would suppress)"
                                        )
                                    break
                        elif element[3] == counting_class and track_id not in self.area_out_list and element[0] <= x:
                            self.area_out_list.append(track_id)

            for element in current_status:
                track_id = element[2]
                cx, cy = element[0], element[1]
                # Record the frame this ID was last seen (for the resurrection /
                # REID-SUPPRESS guards' absence-age computation on the next
                # reappearance), and its first-ever appearance (so REID-SUPPRESS
                # can tell whether another ID appeared during this ID's absence).
                if track_id not in self.first_seen:
                    self.first_seen[track_id] = self.frame_counter
                self.last_seen[track_id] = self.frame_counter

                if track_id not in self.trails:
                    self.trails[track_id] = []
                self.trails[track_id].append((int(cx), int(cy)))

                if len(self.trails[track_id]) > 60:
                    self.trails[track_id].pop(0)
        
        return counter_to_right
