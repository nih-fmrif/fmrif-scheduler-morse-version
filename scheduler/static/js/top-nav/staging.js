const NAV_STAGE_CLASSES = ["nav-stage-2", "nav-stage-3", "nav-stage-4"];
const CENTER_GAP_ENTER_TOLERANCE_PX = 8;
const CENTER_GAP_EXIT_TOLERANCE_PX = 14;
const NON_ICON_GAP_OVERLAP_TOLERANCE_PX = 1;
const ICON_COLLAPSE_ENTER_CENTER_GAP_PX = 90;
const ICON_COLLAPSE_EXIT_CENTER_GAP_PX = 120;
const FINAL_ICON_COMPRESSION_ENTER_CENTER_GAP_PX = 180;
const FINAL_ICON_COMPRESSION_EXIT_CENTER_GAP_PX = 220;

function apply_nav_stage(topInner, stage) {
  topInner.classList.remove(...NAV_STAGE_CLASSES);
  for (let index = 0; index < stage; index += 1) {
    topInner.classList.add(NAV_STAGE_CLASSES[index]);
  }
}

function nav_fits(topInner) {
  return topInner.scrollWidth <= topInner.clientWidth + 1;
}

function read_gap_metrics(topInner) {
  const controls = topInner.querySelectorAll(
    ".header-left > .home-link, .header-left .admin-links > .menu-action, .login-info .user-menu > summary",
  );
  if (controls.length < 4) {
    return null;
  }

  const boxes = Array.from(controls, (control) =>
    control.getBoundingClientRect(),
  );
  const topInnerBox = topInner.getBoundingClientRect();
  return {
    gap12: boxes[1].left - boxes[0].right,
    gap23: boxes[2].left - boxes[1].right,
    gap34: boxes[3].left - boxes[2].right,
    rightSpace: topInnerBox.right - boxes[3].right,
  };
}

function center_gap_is_compressed(metrics, previousStage) {
  // Add hysteresis so we do not flap between expanded and center-compressed
  // while the viewport width hovers near the equal-gap boundary.
  const tolerance =
    previousStage >= 1
      ? CENTER_GAP_EXIT_TOLERANCE_PX
      : CENTER_GAP_ENTER_TOLERANCE_PX;
  return metrics.gap34 <= metrics.gap23 + tolerance;
}

function labels_can_remain_visible(metrics, previousStage) {
  if (metrics == null) {
    return true;
  }
  const threshold =
    previousStage >= 2
      ? ICON_COLLAPSE_EXIT_CENTER_GAP_PX
      : ICON_COLLAPSE_ENTER_CENTER_GAP_PX;
  return metrics.gap34 > threshold;
}

function non_icon_layout_is_valid(metrics, previousStage) {
  return (
    metrics.gap34 >= metrics.gap23 - NON_ICON_GAP_OVERLAP_TOLERANCE_PX &&
    labels_can_remain_visible(metrics, previousStage)
  );
}

function should_enter_final_icon_compression(metrics, previousStage) {
  const threshold =
    previousStage >= 3
      ? FINAL_ICON_COMPRESSION_EXIT_CENTER_GAP_PX
      : FINAL_ICON_COMPRESSION_ENTER_CENTER_GAP_PX;
  return metrics.gap34 <= threshold;
}

function pick_base_stage(metrics, previousStage) {
  if (metrics == null) {
    return 0;
  }
  if (center_gap_is_compressed(metrics, previousStage)) {
    return 1;
  }
  return 0;
}

function pick_nav_stage(topInner, previousStage) {
  const maxStage = NAV_STAGE_CLASSES.length;
  apply_nav_stage(topInner, 0);
  const baselineMetrics = read_gap_metrics(topInner);
  let chosenStage = pick_base_stage(baselineMetrics, previousStage);
  apply_nav_stage(topInner, chosenStage);

  while (chosenStage < maxStage) {
    const metrics = read_gap_metrics(topInner);
    const fits = nav_fits(topInner);
    let phaseReady = true;
    if (metrics != null) {
      if (chosenStage === 1) {
        phaseReady = non_icon_layout_is_valid(metrics, previousStage);
      } else if (chosenStage === 2) {
        phaseReady = !should_enter_final_icon_compression(
          metrics,
          previousStage,
        );
      }
    }
    if (fits && phaseReady) {
      break;
    }

    chosenStage += 1;
    apply_nav_stage(topInner, chosenStage);
  }

  apply_nav_stage(topInner, chosenStage);
  return chosenStage;
}

function wire_top_nav_staging() {
  const topInner = document.querySelector(".top-inner");
  if (!topInner) {
    return;
  }

  let rafId = 0;
  let currentStage = 0;
  const schedule = () => {
    if (rafId) {
      return;
    }
    rafId = window.requestAnimationFrame(() => {
      rafId = 0;
      currentStage = pick_nav_stage(topInner, currentStage);
    });
  };

  schedule();
  window.addEventListener("resize", schedule, { passive: true });

  if ("ResizeObserver" in window) {
    const observer = new ResizeObserver(schedule);
    observer.observe(topInner);
  }

  if ("fonts" in document && document.fonts && "ready" in document.fonts) {
    document.fonts.ready.then(schedule).catch(() => {
      // The initial schedule still applies; ignore font readiness failures.
    });
  }
}

export { wire_top_nav_staging };
