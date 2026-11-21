(function (root, factory) {
  const guru = factory();
  if (typeof module === "object" && module.exports) module.exports = guru;
  else root.LifePilotGuru = guru;
})(globalThis, function () {
  "use strict";

  const slot = (start, end, en, zh) => ({ start, end, name: [en, zh] });
  const hyperTopics = [
    ["Redesign your portfolio", "重做作品集"], ["Review tomorrow’s investments", "复盘明天的投资组合"],
    ["Mobility drills", "做灵活性训练"], ["Rewrite the sales pitch", "重写销售话术"],
    ["Clear messages", "清空消息"], ["Practice pronunciation", "练习外语发音"],
    ["Draft a sprint plan", "起草冲刺计划"], ["Sort receipts", "整理发票"],
    ["Read a research abstract", "精读研究摘要"], ["Edit a short video", "剪一条短视频"],
    ["Review your step count", "复盘步数"], ["Outline a newsletter", "列一份通讯提纲"],
    ["Practice speed reading", "练习速读"], ["Restructure the budget", "重排预算"],
    ["Practice a mock interview", "模拟面试"], ["Reorganize files", "重建文件目录"],
    ["Study negotiation", "练习谈判"], ["Review the KPI board", "刷新 KPI 面板"],
  ];
  const hyperBlocks = [
    slot(300, 315, "Listen to an industry podcast", "听播客吸收行业前沿"),
    slot(315, 330, "Reply to international email", "回复国际邮件"),
    slot(330, 345, "High-intensity interval training", "高强度 HIIT 锻炼"),
    slot(345, 360, "Memorize 50 words", "背诵 50 个单词"),
    ...Array.from({ length: 71 }, (_, i) => slot(360 + i * 15, 375 + i * 15, ...hyperTopics[i % hyperTopics.length])),
    slot(1425, 1740, "Efficient sleep", "高效睡眠"),
  ];

  const TEMPLATES = {
    mountain: {
      id: "mountain",
      guru: ["The Minimalist Ascetic", "极简修行大师"],
      title: ["Mountain Retreat · The Anti-Internet Routine", "深山修道·反互联网作息"],
      price: ["Free · with ads", "免费 · 含广告"],
      pitch: ["Go offline. Check in on the app. The guru expects both.", "大师要求你断网，同时要求你在 App 里打卡。"],
      blocks: [
        slot(240, 360, "Morning meditation", "晨间冥想"),
        slot(360, 720, "Uninterrupted focus", "连续专注"),
        slot(720, 735, "Vegetarian meal", "进食（仅限素食）"),
        slot(735, 1320, "High-intensity chores", "高强度杂务"),
        slot(1320, 1680, "Sleep with simulated monitoring", "睡眠（模拟监测）"),
      ],
    },
    hyper: {
      id: "hyper",
      guru: ["The 10M-Follower Efficiency Influencer", "千万粉效率大V"],
      title: ["HYPER · The Ultimate Fragmented Parallel Method", "HYPER 碎片化并行终极法"],
      price: ["¥199 / month · HYPER Premium", "¥199 / 月 · HYPER Premium"],
      pitch: ["Switch tasks every 15 minutes. At bedtime, even rest gets its own guru soundtrack.", "每 15 分钟切换一次任务。睡觉也得听大师安排。"],
      blocks: hyperBlocks,
    },
    slack: {
      id: "slack",
      guru: ["The Godfather of Workplace Slacking", "职场反卷教父"],
      title: ["Parkinson’s Guide to Slacking", "帕金森摸鱼大法"],
      price: ["Free · paid advanced tips", "免费 · 高级技巧付费解锁"],
      pitch: ["Stretch one hour of work into a full day. The deadlines stay where they were.", "把 1 小时的工作拖成一整天，截止时间照旧。"],
      blocks: [
        slot(540, 600, "Get into work mode · coffee and desk tidying", "准备进入工作状态（泡咖啡、整理桌面）"),
        slot(600, 660, "Look for inspiration · bathroom break and headlines", "寻找灵感（带薪如厕、浏览新闻）"),
        slot(660, 720, "Warm up · open the document and stare for 45 minutes", "预热核心任务（打开文档，发呆 45 分钟）"),
        slot(780, 1020, "Deep slacking and microexpression management", "深度摸鱼与微表情管理"),
        slot(1020, 1080, "Last-minute sprint", "极限赶工冲刺"),
      ],
    },
  };

  const SLACK_TASKS = [
    ["Finish the project brief", "完成项目简报"],
    ["Proofread the deliverable", "校对交付稿"],
    ["Send it to the team", "把交付稿发给团队"],
  ];
  const SLEEP_VOICE = [
    "Welcome to efficient sleep. Please leave tomorrow's productivity rating running while you rest.",
    "欢迎进入高效睡眠。请保持效率评分开启，祝你睡得足够高效。",
  ];

  const COURSE_PROMOTIONS = {
    hyper: [
      "Turn every 15 minutes into a new sprint. One subscription gives you 75 slots to optimize.",
      "每 15 分钟开启一次冲刺。一份订阅，给你 75 个可以优化的时段。",
    ],
    mountain: [
      "Start at 04:00, go offline, and remember to check in. The retreat is free with ads.",
      "04:00 起床修行，断网专注，记得上线打卡。课程免费，内含广告。",
    ],
    slack: [
      "Fill eight hours with one hour’s work. Advanced tips are available as a paid unlock.",
      "用一小时的工作填满八小时。进阶摸鱼技巧可付费解锁。",
    ],
  };

  const MARKETPLACE_PRICE = ["$12 / month · simulated", "$12 / 月 · 模拟"];
  const MARKETPLACE_TEMPLATES = [
    {
      id: "deep-work-master-plan",
      title: ["Deep Work Master Plan", "深度工作计划"],
      tier: "free",
      description: [
        "Protect two long focus blocks each day and let shallow work fill the gaps.",
        "每天留出两个长时专注时段，把杂务安排在间隙。",
      ],
      benefits: [
        ["Two protected focus blocks per workday", "每个工作日保留两个专注时段"],
        ["Shallow-work window after lunch", "午饭后的杂务时段"],
        ["Weekly review checklist", "每周复盘清单"],
      ],
      preview: [
        ["Mon · 09:00–11:00 · Deep work sprint", "周一 · 09:00–11:00 · 深度工作冲刺"],
        ["Mon · 14:00–15:00 · Shallow work batch", "周一 · 14:00–15:00 · 集中处理杂务"],
        ["Tue · 09:00–11:00 · Deep work sprint", "周二 · 09:00–11:00 · 深度工作冲刺"],
        ["Wed · 09:00–10:30 · Deep work sprint", "周三 · 09:00–10:30 · 深度工作冲刺"],
      ],
    },
    {
      id: "exam-preparation-system",
      title: ["Exam Preparation System", "考试备考系统"],
      tier: "premium",
      description: [
        "Turn a syllabus into spaced revision sessions with protected practice time.",
        "按考试大纲安排间隔复习，并为练习留出固定时间。",
      ],
      benefits: [
        ["Spaced repetition across every subject", "覆盖各科的间隔复习"],
        ["Practice-test blocks with review buffers", "模拟测试和讲评预留时间"],
        ["Daily minimum revision target", "每日最低复习目标"],
        ["Exam-week fallback plan", "考试周备用计划"],
      ],
      preview: [
        ["Mon · 18:00–19:30 · Calculus practice set", "周一 · 18:00–19:30 · 微积分练习"],
        ["Tue · 07:30–08:15 · Flashcards review", "周二 · 07:30–08:15 · 复习记忆卡片"],
        ["Wed · 18:00–19:30 · Mock paper", "周三 · 18:00–19:30 · 模拟试卷"],
        ["Thu · 07:30–08:15 · Error log review", "周四 · 07:30–08:15 · 复盘错题"],
      ],
    },
    {
      id: "ultimate-productivity-routine",
      title: ["Ultimate Productivity Routine", "终极效率作息"],
      tier: "premium",
      description: [
        "A high-intensity weekly routine that balances deep work, admin and recovery.",
        "在高强度的一周里安排深度工作、日常事务和休息。",
      ],
      benefits: [
        ["Adaptive priority triage", "动态调整优先级"],
        ["Recovery and buffer blocks", "恢复与缓冲时段"],
        ["Deadline risk radar", "截止日期风险检查"],
        ["Friday shutdown ritual", "周五收尾流程"],
      ],
      preview: [
        ["Mon · 08:30–10:30 · Priority deep work", "周一 · 08:30–10:30 · 优先处理深度工作"],
        ["Mon · 16:00–16:45 · Admin sweep", "周一 · 16:00–16:45 · 清理日常事务"],
        ["Tue · 08:30–10:30 · Priority deep work", "周二 · 08:30–10:30 · 优先处理深度工作"],
        ["Fri · 16:00–16:45 · Weekly shutdown", "周五 · 16:00–16:45 · 一周收尾"],
      ],
    },
    {
      id: "elite-weekly-planner",
      title: ["Elite Weekly Planner", "精英周计划"],
      tier: "free",
      description: [
        "Start every week with a realistic capacity check and a clear top-three list.",
        "每周先评估可用时间，再明确三项最重要的目标。",
      ],
      benefits: [
        ["Top-three weekly outcomes", "本周三项重点成果"],
        ["Capacity check before committing", "接下任务前检查可用时间"],
        ["Sunday planning ritual", "周日规划流程"],
      ],
      preview: [
        ["Sun · 19:00–19:30 · Weekly reset", "周日 · 19:00–19:30 · 整理下周计划"],
        ["Mon · 08:45–09:00 · Top-three review", "周一 · 08:45–09:00 · 确认三项重点"],
        ["Wed · 17:00–17:15 · Midweek check-in", "周三 · 17:00–17:15 · 检查本周进度"],
        ["Fri · 16:30–16:45 · Close the week", "周五 · 16:30–16:45 · 本周总结"],
      ],
    },
  ];

  function marketplaceState(state) {
    const saved = state.guruMarketplace;
    return {
      tier: saved?.tier === "premium" ? "premium" : "free",
      selectedTemplateId: saved?.selectedTemplateId ?? null,
    };
  }

  function marketplaceCatalog(state) {
    const membership = marketplaceState(state);
    return MARKETPLACE_TEMPLATES.map((template) => {
      const locked = template.tier === "premium" && membership.tier === "free";
      return {
        ...template,
        locked,
        selected: !locked && membership.selectedTemplateId === template.id,
        preview: locked ? template.preview.slice(0, 2) : template.preview,
      };
    });
  }

  function setMarketplaceTier(state, tier) {
    const membership = marketplaceState(state);
    if ((tier !== "free" && tier !== "premium") || tier === membership.tier) return {};
    state.guruMarketplace = { ...membership, tier };
    return { updated: true };
  }

  function selectMarketplaceTemplate(state, id) {
    const template = marketplaceCatalog(state).find((item) => item.id === id);
    if (!template || template.selected) return {};
    if (template.locked) return { locked: true };
    state.guruMarketplace = { ...marketplaceState(state), selectedTemplateId: id };
    return { updated: true };
  }

  function takeCoursePromotion(state, day = null) {
    const previous = state.coursePromotions;
    if (day && (!state.user.onboardingCompleted || state.preferences.paused ||
      !state.preferences.optional || previous?.shownOn === day)) return {};
    const courses = Object.keys(COURSE_PROMOTIONS);
    const cursor = previous?.next || 0;
    state.coursePromotions = { shownOn: day || previous?.shownOn || null, next: (cursor + 1) % courses.length };
    return { updated: true, course: courses[cursor] };
  }

  const clock = (minutes) => {
    const minuteOfDay = minutes % 1440;
    return [Math.floor(minuteOfDay / 60), minuteOfDay % 60].map((n) => String(n).padStart(2, "0")).join(":");
  };

  function update(state, id, action) {
    if (!Object.hasOwn(TEMPLATES, id)) return {};
    const template = TEMPLATES[id];
    let run = state.guru?.[id];
    if (action === "unlock") {
      if (id === "mountain" || run?.unlocked) return {};
      state.guru ||= {};
      state.guru[id] = { ...run, unlocked: true };
      return { updated: true };
    }
    if (action === "start") {
      if (id === "hyper" && !run?.unlocked) return {};
      state.guru ||= {};
      state.guru[id] = {
        unlocked: Boolean(run?.unlocked), step: 0, done: false,
        ...(id === "mountain" ? { offline: true, checkedIn: false, efficiency: 100, turns: 0 } : {}),
        ...(id === "slack" ? { overdue: false } : {}),
      };
      return { updated: true, guruAd: id === "mountain", guruStopVoice: id === "hyper" };
    }
    if (run?.step === undefined || run.done) return {};

    const alerts = [];
    const alert = (type, title, message) => alerts.push({ type, title, message });
    let guruVoice = false;
    let guruStopVoice = false;

    if (id === "mountain" && action === "network" && run.step === 0) {
      run.offline = !run.offline;
      if (!run.offline) alert("pressure", ["Connection violates retreat rules", "联网违反修行规定"],
        ["The meditation button works again. Your guru still expects you to be offline.", "冥想按钮恢复可用，但大师仍要求你断网。"]);
    } else if (id === "mountain" && action === "meditate" && run.step === 0) {
      if (run.checkedIn) return {};
      if (run.offline) alert("pressure", ["Check-in blocked", "打卡失败"],
        ["The app requires a connection to start meditation.", "App 要求联网才能开始冥想。"]);
      else {
        run.checkedIn = true;
        alert("task", ["Meditation checked in", "冥想已打卡"], ["The app recorded your start.", "App 已记录开始。"]);
      }
    } else if (id === "mountain" && action === "break" && run.step === 1) {
      alert("pressure", ["Break denied", "休息被拒绝"],
        ["The guru requires uninterrupted focus until noon.", "大师要求一直专注到中午，期间不允许休息。"]);
    } else if (id === "mountain" && action === "turn" && run.step === 4) {
      run.turns += 1;
      if (run.turns === 3) alert("pressure", ["Sleep discipline warning", "睡眠自律警告"],
        ["Three simulated turns detected. The guru says you could be more disciplined.", "模拟监测到三次翻身。大师说你还不够自律。"]);
    } else if (action === "next" || (id === "hyper" && action === "sleep" && run.step < template.blocks.length - 1)) {
      if (id === "mountain" && run.step === 0 && !run.checkedIn) {
        run.efficiency -= 10;
        alert("pressure", ["Missed check-in · −10 efficiency", "冥想未打卡 · 效率分 −10"],
          ["The 06:00 deadline passed without an app check-in.", "06:00 已到，系统没有收到 App 打卡。"]);
      }

      const end = template.blocks.length - 1;
      if (run.step === end) {
        run.done = true;
        if (id === "hyper") guruStopVoice = true;
        if (id === "slack") {
          run.overdue = true;
          for (const task of SLACK_TASKS) alert("task", ["Task overdue", "任务逾期"], task);
        }
      } else {
        run.step = action === "sleep" ? end : run.step + 1;
        if (id === "hyper" && run.step === end) {
          guruVoice = true;
          alert("pressure", ["Guru sleep voice started", "大师催眠语音已触发"],
            ["The Premium routine starts its sleep audio automatically.", "进入睡眠时段后，Premium 作息自动播放语音。"]);
        } else if (id === "hyper" && run.step === 50) {
          alert("pressure", ["50 task switches logged", "已切换 50 次任务"],
            ["Your guru thinks you can still squeeze in more.", "大师觉得你还能再挤进几个任务。"]);
        }
        if (id === "slack" && run.step === end) alert("pressure", ["Deadline approaching", "截止时间逼近"],
          ["Three unfinished tasks. One hour left.", "还剩一小时，三个任务都没完成。"]);
      }
    } else {
      return {};
    }

    if (alerts.length) run.alerts = [...alerts].reverse().concat(run.alerts || []).slice(0, 8);
    return { updated: true, guruAlerts: alerts, guruVoice, guruStopVoice };
  }

  return {
    TEMPLATES, SLACK_TASKS, SLEEP_VOICE, COURSE_PROMOTIONS, takeCoursePromotion, clock, update,
    MARKETPLACE_PRICE, marketplaceState, marketplaceCatalog, setMarketplaceTier, selectMarketplaceTemplate,
  };
});
