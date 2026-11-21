(function () {
  "use strict";

  const G = window.LifePilotGuru;
  const media = window.LifePilotGuruMedia;
  const portraitSource = "https://commons.wikimedia.org/wiki/File:Elon_Musk_Royal_Society_(cropped).jpg";
  const license = "https://creativecommons.org/licenses/by-sa/3.0/";

  window.LifePilotGuruView = function ({ state, selection, audioStatus, t, button, e }) {
    const tt = (words) => t(...words);
    const nextDay = (value) => value >= 1440 ? t(" (next day)", "（次日）") : "";
    const clock = (value) => G.clock(value) + nextDay(value);
    const select = (title, id, cls) => button(title, "guru-open", cls, `data-template="${id}"`);
    const action = (title, name, cls = "lp-outline") => button(title, "guru-action", cls, `data-guru-action="${name}"`);
    const portrait = () => `<figure class="lp-guru-portrait"><img alt="${t("Color portrait of Elon Musk", "马斯克彩色肖像")}" src="${media.portrait}" width="377" height="503">
      <figcaption>${t("Public portrait · fictional demo role", "公开肖像 · 虚构演示角色")}<br>
        <a href="${portraitSource}" target="_blank" rel="noopener noreferrer">${t("The Royal Society photo", "英国皇家学会照片")}</a> · <a href="${license}" target="_blank" rel="noopener noreferrer">CC BY-SA 3.0</a>
      </figcaption></figure>`;

    function marketplace() {
      const current = state();
      const premium = G.marketplaceState(current).tier === "premium";
      return `<section class="lp-marketplace" aria-labelledby="lp-marketplace-title">
        <div class="lp-marketplace-heading">
          <h2 id="lp-marketplace-title">${t("Template Marketplace", "模板市场")}</h2>
          <div class="lp-inline-actions">
            <span class="lp-marketplace-badge lp-marketplace-plan" role="status">${premium
              ? t("Marketplace Premium · Demo", "市场 Premium · 模拟")
              : t("Marketplace Free", "市场免费版")}</span>
            ${premium ? button(t("Return to Free plan", "降回免费版"), "marketplace-downgrade", "lp-subtle") : ""}
          </div>
        </div>
        <div class="lp-marketplace-grid">
          ${G.marketplaceCatalog(current).map((template) => `
            <article class="lp-card lp-marketplace-card" aria-labelledby="lp-market-${template.id}">
              <div class="lp-marketplace-labels">
                <span class="lp-marketplace-badge ${template.locked ? "lp-marketplace-locked" : ""}">${template.tier === "free"
                  ? t("Free", "免费")
                  : template.locked ? t("Premium · Locked", "Premium · 已锁定") : t("Premium · Unlocked", "Premium · 已解锁")}</span>
                ${template.selected ? `<span class="lp-marketplace-badge">${t("Selected", "已选择")}</span>` : ""}
              </div>
              <h3 id="lp-market-${template.id}">${e(tt(template.title))}</h3>
              <p>${e(tt(template.description))}</p>
              ${button(template.locked ? t("Preview locked template", "预览锁定模板") : t("Preview template", "预览模板"),
                "marketplace-preview", "lp-outline", `data-market-template="${template.id}" aria-haspopup="dialog"`)}
            </article>`).join("")}
        </div>
      </section>`;
    }

    function gallery() {
      return `<section class="lp-feature lp-guru">
        <div class="lp-page-heading"><div><h1>${t("Guru Templates", "大师模板")}</h1>
          <p class="lp-page-description">${t("Preview weekly templates or try an interactive routine.", "预览每周模板，或试跑互动课程。")}</p></div>
          <div class="lp-inline-actions">
            ${button(t("Back to Weekly Calendar", "返回周历"), "navigate", "lp-subtle", 'data-route="calendar"')}
            ${button(t("Preview course ad", "预览课程广告"), "guru-preview-ad", "lp-outline")}
          </div></div>
        ${marketplace()}
        <section class="lp-guru-routines" aria-labelledby="lp-guru-routines-title">
          <h2 id="lp-guru-routines-title">${t("Interactive routines", "互动课程")}</h2>
          <div class="lp-guru-grid">${Object.values(G.TEMPLATES).map((template) =>
          `<article class="lp-card lp-guru-card lp-guru-${template.id}">
            <div class="lp-guru-card-top"><p class="lp-guru-name">${tt(template.guru)}</p>
              <h2>${tt(template.title)}</h2><p class="lp-guru-price">${tt(template.price)}</p>
            </div>
            <div class="lp-guru-card-body">
              ${template.id === "hyper" ? portrait() : ""}
              <p>${tt(template.pitch)}</p>
              ${select(t("View routine", "查看作息"), template.id, "lp-outline")}
            </div>
          </article>`).join("")}</div>
        </section>
      </section>`;
    }

    function timeline(template, run) {
      return `<section class="lp-card lp-guru-timeline">
         <h2>${t("Daily routine", "一天作息")}</h2>
         <div class="lp-guru-timeline-scroll" tabindex="0" aria-label="${t("Routine time slots", "作息时间段")}">
           <ol>${template.blocks.map((block, index) => `<li ${(!run?.done && run?.step === index) ? 'aria-current="step"' : ""}>
            <time>${G.clock(block.start)} – ${clock(block.end)}</time><span>${tt(block.name)}</span>
           </li>`).join("")}</ol>
         </div>
      </section>`;
    }

    function runDetails(template, run) {
      const id = template.id;
      if (!Number.isInteger(run?.step)) return `<p class="lp-muted">${t("Start the demo to move through this routine on a simulated clock.", "启动演示，用模拟时钟体验这套作息。")}</p>`;
      const block = template.blocks[run.step];
      const now = run.done ? block.end : block.start;
      let controls = "";
      if (id === "mountain") {
        controls = `<dl class="lp-guru-metrics">
          <div><dt>${t("Efficiency", "效率分")}</dt><dd>${run.efficiency}</dd></div>
          <div><dt>${t("Simulated connection", "模拟网络")}</dt><dd>${run.offline ? t("Offline", "已断网") : t("Online", "已联网")}</dd></div>
          ${run.step === 4 ? `<div><dt>${t("Simulated turns", "模拟翻身")}</dt><dd>${run.turns}</dd></div>` : ""}
        </dl><div class="lp-inline-actions">${!run.done && run.step === 0 ?
          action(t("Start meditation", "开始冥想"), "meditate", "lp-outline" + (run.checkedIn ? " lp-done-control" : "")) +
          action(run.offline ? t("Simulate reconnect", "模拟恢复联网") : t("Simulate disconnect", "模拟断网"), "network")
          : !run.done && run.step === 1 ? action(t("Take a break", "休息"), "break")
            : !run.done && run.step === 4 ? action(t("Simulate turning over", "模拟翻身"), "turn") : ""}</div>`;
      }
      if (id === "hyper") {
        const daytime = template.blocks.length - 1;
        const count = Math.min(run.step, daytime - 1);
        controls = `<dl class="lp-guru-metrics"><div><dt>${t("Task switches", "已切换任务")}</dt><dd>${count}</dd></div>
           <div><dt>${t("15-minute slots", "15 分钟时段")}</dt><dd>${daytime}</dd></div></dl>`;
        if (run.step === daytime && !run.done) {
          const status = {
            playing: t("Guru sleep audio is playing.", "正在播放大师睡前语音。"),
            ended: t("Guru sleep audio finished.", "大师睡前语音已播放完毕。"),
            blocked: t("Autoplay was blocked. Select Play voice to listen.", "浏览器阻止了自动播放，点「播放语音」即可收听。"),
            stopped: t("Guru sleep audio stopped.", "大师睡前语音已停止。"),
          }[audioStatus()];
          controls += `<section class="lp-guru-voice"><strong>${t("Guru sleep voice · scripted narration", "大师催眠曲 · 合成旁白")}</strong>
            <p>${tt(G.SLEEP_VOICE)}</p>
            ${status ? `<p role="status">${status}</p>` : ""}
            <div class="lp-inline-actions">
              ${button(t("Play voice", "播放语音"), "guru-play", "lp-outline")}
              ${button(t("Stop voice", "停止语音"), "guru-stop", "lp-subtle")}
            </div></section>`;
        }
      }
      if (id === "slack") {
        controls = `<ul class="lp-guru-deadlines">${G.SLACK_TASKS.map((task) => `<li>
          <span>${tt(task)}</span><strong>${run.overdue ? t("Overdue", "已逾期") : t("Due 18:00", "18:00 到期")}</strong>
        </li>`).join("")}</ul>`;
      }
      return `<div class="lp-guru-clock"><span>${t("Simulated time", "模拟时间")}</span><strong>${clock(now)}</strong></div>
        <p class="lp-guru-current">${run.done ? t("Demo day finished", "演示日结束") : tt(block.name)}</p>
        ${controls}
        ${!run.done ? `<div class="lp-inline-actions lp-guru-advance">
           ${action(id === "hyper" && run.step < template.blocks.length - 1 ? t("Advance 15 minutes", "推进 15 分钟") : t("Advance time", "推进时间"), "next", "lp-primary")}
           ${id === "hyper" && run.step < template.blocks.length - 1 ? action(t("Jump to 23:45 sleep", "快进到 23:45 睡眠"), "sleep") : ""}
         </div>` : ""}
      `;
    }

    function detail(template) {
      const id = template.id;
      const run = state().guru?.[id];
      const started = Number.isInteger(run?.step);
      const locked = id === "hyper" && !run?.unlocked;
      return `<section class="lp-feature lp-guru">
        <div class="lp-page-heading lp-guru-heading"><div>
          ${button(t("All templates", "全部模板"), "guru-gallery", "lp-outline")}
          <p class="lp-guru-name">${tt(template.guru)}</p>
          <h1>${tt(template.title)}</h1><p class="lp-page-description">${tt(template.pitch)}</p>
        </div></div>
        <div class="lp-guru-detail"><div class="lp-guru-run-stack">
          <section class="lp-card lp-guru-run">
            <div class="lp-guru-section-head"><h2>${t("Run the template", "试跑模板")}</h2><span class="lp-demo-badge">${t("Demo", "演示")}</span></div>
            ${id === "hyper" ? portrait() : ""}
            <p class="lp-guru-price">${tt(template.price)}</p>
            <div class="lp-inline-actions">
              ${locked
                ? action(t("Simulate HYPER unlock", "模拟解锁 HYPER"), "ask-unlock", "lp-primary")
                : action(started ? t("Restart routine", "重启作息") : t("Start routine", "启动作息"), "start", started ? "lp-subtle" : "lp-primary")}
              ${id === "slack" && !run?.unlocked ? action(t("Unlock advanced tips (demo)", "模拟付费解锁高级技巧"), "ask-unlock") : ""}
            </div>
            ${run?.unlocked ? `<p class="lp-muted">${id === "hyper" ? t("HYPER unlocked for this demo.", "HYPER 已在演示中解锁。") : t("Advanced tip: rename procrastination ‘preparation’.", "高级技巧：把拖延改名为「准备工作」。")}</p>` : ""}
            ${runDetails(template, run)}
          </section>
          ${run?.alerts?.length ? `<section class="lp-card lp-guru-alerts" aria-label="${t("Routine feedback", "作息反馈")}"><h2>${t("Routine feedback", "作息反馈")}</h2>
            <ol>${run.alerts.map((alert) => `<li><strong>${e(tt(alert.title))}</strong><p>${e(tt(alert.message))}</p></li>`).join("")}</ol>
          </section>` : ""}
        </div>${timeline(template, run)}</div>
      </section>`;
    }

    return () => selection() && Object.hasOwn(G.TEMPLATES, selection()) ? detail(G.TEMPLATES[selection()]) : gallery();
  };
})();
