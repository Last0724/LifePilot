(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory;
  else root.createLifePilotChatMock = factory;
})(globalThis, function createChatMock(options) {
  "use strict";

  const { t, weekStart, addDays } = options;
  // These are sample blocks for the UI demo. This adapter does not interpret prose or find time slots.
  const slots = [
    [0, "09:30", "10:45"], [1, "10:00", "11:00"], [3, "10:00", "11:00"],
  ];

  function fixtures(week) {
    return {
      goal: t("Finish my presentation deck", "完成演示文稿"),
      tasks: [
        { title: t("Draft the presentation", "起草演示文稿"), details: t("75 minutes of focus", "专注 75 分钟") },
        { title: t("Rehearse the presentation", "排练演示"), details: t("60 minutes before Thursday", "周四前留出 60 分钟") },
      ],
      commitments: [{ title: t("Project check-in", "项目例会"), date: addDays(week, 2), startTime: "14:00", endTime: "14:30" }],
      wake: "07:30", bed: "23:00", workStart: "09:00", workEnd: "17:30",
      rest: t("Keep lunch free for a break.", "午饭时间留给休息。"),
      routine: t("Leave evenings open for a walk.", "晚上留一点时间散步。"),
    };
  }

  function exampleMessage(state) {
    switch (state?.turn ?? 0) {
      case 0:
        return t("I want to finish my presentation deck this week. I need about 75 minutes to draft it and an hour to rehearse before Thursday.",
          "我这周想完成演示文稿，起草需要大约 75 分钟，周四前还想留一个小时排练。");
      case 1:
        return t("I have a project check-in on Wednesday from 2 to 2:30 PM. I usually work from 9 AM to 5:30 PM.",
          "周三下午两点到两点半有项目例会。我通常早上九点到下午五点半工作。");
      case 2:
        return t("I get up at 7:30 and go to bed at 11. Please leave lunch free and give me time to walk in the evenings.",
          "我早上七点半起床，晚上十一点睡。午饭时间想休息，晚上也想留点时间散步。");
      default:
        return "";
    }
  }

  async function handle_chat_message(message, state) {
    if (!message.trim()) throw new Error("A chat message is required.");
    const week = state?.week ?? weekStart();
    const turn = (state?.turn ?? 0) + 1;
    const sample = fixtures(week);
    const next = { state: { week, turn }, ready: false };
    if (turn === 1) {
      return { ...next, fields: { goal: sample.goal, tasks: sample.tasks },
        reply: t("The sample goal and tasks are in the summary. What fixed commitments or usual work hours should I account for?",
          "摘要里已有示例目标和任务。你有哪些时间固定的安排？通常几点到几点工作？") };
    }
    if (turn === 2) {
      const { goal, tasks, commitments, workStart, workEnd } = sample;
      return { ...next, fields: { goal, tasks, commitments, workStart, workEnd },
        reply: t("The sample commitment and work hours are in the summary. When do you sleep, and what breaks or routines should I keep in mind?",
          "摘要已加入示例固定安排和工作时间。你通常几点睡、几点起？有什么想保留的休息时间或日常习惯？") };
    }
    if (turn === 3) {
      return { ...next, ready: true, fields: sample,
        reply: t("The sample is ready to review. Edit the fields to match your week, then confirm to see a demo schedule.",
          "示例信息已整理好。请把卡片改成符合你的实际情况，再确认生成演示周计划。") };
    }
    return { ...next, ready: true,
      reply: t("That message is in the conversation. In this preview, you can record changes directly in the confirmation card.",
        "这条消息已加入对话。演示里可以直接在确认卡片中记录这次修改。") };
  }

  async function build_confirmed_schedule(state, fields) {
    if (!state || state.turn < 3) throw new Error("The example conversation has not reached confirmation.");
    if (fields.tasks.length > slots.length) throw new Error("The fixture contains three task slots.");
    const booked = fields.commitments.map(({ title, date, startTime, endTime }) => ({
      title, date, startTime, endTime, category: "Work", priority: "Medium",
    }));
    const planned = fields.tasks.map(({ title }, index) => {
      const [day, startTime, endTime] = slots[index];
      return { title, date: addDays(state.week, day), startTime, endTime, category: "Study", priority: "Medium" };
    });
    return { entries: [...booked, ...planned] };
  }

  return { handle_chat_message, build_confirmed_schedule, exampleMessage, taskLimit: slots.length };
});
