# LifePilot

LifePilot is a local productivity planner and competition demo. It puts a real weekly schedule alongside simulated XP, leaderboard competition, and repeated in-site notifications.

## Run locally

From the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install streamlit==1.55.0
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8511
```

Open [LifePilot](http://127.0.0.1:8511/). The previous Streamlit entrypoint, `python -m streamlit run ui/preview.py`, also launches this experience. The planner runs locally without API credentials. Use **中文 / EN** to switch languages.

Use the root URL when sharing a preview. Every open or refresh starts at the cat welcome page with local display-name sign-in. After sign-in, first-time users complete the three numbered setup steps and returning users resume their saved calendar.

## Competition walkthrough

1. Open LifePilot and use **Sign in** after the pixel cat arrives. If the browser already has a schedule and you want to start over, open **Settings → Reset Demo**, confirm, and sign in again.
2. Set your daily routine, add at least one activity with a day and time, and enter a weekly goal. The seven-day preview updates when you add, edit, or delete activities. **Generate My Schedule** opens the calendar using your entries.
3. Click **Start Demo** in the calendar’s Notifications card. Complete a task before the fifth timed notification to see XP increase and simulated competitors move ahead. The full leaderboard shows the same ranks as the calendar summary.
4. Keep the calendar open to see the eight-message sequence at roughly six-second intervals. Close a toast to dismiss it or click it to open the related feature. **Notifications** keeps the history and unread count.
5. Use **Settings → Replay Notification Demo** to replay, **Pause Notifications** to pause in-site delivery, or turn off optional reminders to suppress the scripted sequence. **Stop Demo** returns to normal reminder behavior. Switching away from the calendar suspends the timed sequence until you return.

For an actionable walkthrough, create three activities across separate days, one with **High** priority. Add a second activity on the first day if you want the first completion to show a standalone +10 XP without a daily bonus. Demo resets restore the starting competitor scores for a fresh rank-drop demonstration.

## State and rewards

The browser stores one schedule, completion state, points ledger, simulated competitor dataset, and notification history per site origin. Sign-in resumes the saved schedule after a refresh or reopen. A recurring activity has independent completion state for each week. Editing or deleting a recurring task applies to the series.

| Action | XP |
| --- | ---: |
| Complete a normal task | 10 |
| Complete a high-priority task | 20 |
| Complete all scheduled tasks on a date | 30 |
| Complete all scheduled tasks in a week | 100 |
| First schedule check each local day | 2 |

Points history records each reward once. Reopening or deleting a task keeps prior rewards in the ledger. Completing an occurrence again cannot reclaim its reward. Level is `1 + floor(XP / 200)`. Ranks include 24 simulated competitors and sort by XP descending, then by stable user ID. In Demo Mode, simulated competitors can receive enough XP to change the actual order.

The previous consultation, demo sign-in, optimization, templates, and ranking prototype are available under **Settings → Classic AI consultation and demo features**. That preview uses its own demo data and simulated voice transcript.

## Guru Templates

After setup, open **Guru Templates** from the main navigation. Each program runs against a simulated clock. Its progress is stored in the browser alongside the rest of the demo. The programs use sample activities and a separate efficiency score. Their optional warnings also appear in Notification Center.

The calendar can show one course offer per local day when optional reminders are enabled and notifications are active. The free retreat also opens a course ad at the start of its simulation. **Guru Templates → Preview course ad** opens an offer on demand. **View course** opens the promoted routine, and **Maybe later** dismisses the offer.

- **Mountain Retreat** opens a mock ad. Start meditation with the simulated connection offline, then advance past 06:00 to see the missed-check-in penalty. Try taking a break during focus and simulate turning over three times during sleep.
- **HYPER** uses a simulated ¥199/month Premium gate. Advance 15 minutes at a time, or jump to 23:45 to hear the fictional sleep narration. There are 75 daytime slots, ending at the specified sleep start.
- **Parkinson’s Guide to Slacking** offers a simulated advanced-tip unlock. Advance through the last-minute sprint to see the three sample tasks become overdue and produce alerts.

The color portrait is used in a fictional satire demo. Photo by Duncan Hull, credited to The Royal Society, cropped for display. [Portrait source](https://commons.wikimedia.org/wiki/File:Elon_Musk_Royal_Society_(cropped).jpg) · [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/).

## Verification

Run the planner's core tests with Node.js:

```sh
node --test tests/*.test.js
```

The tests cover task validation and recurring conflicts, once-only XP, recurring completion, ranking, delivery pacing, notification preferences, and normal task reminders.

## Frontend checkpoints

Commit and push independently testable milestones to `origin/feature/frontend`. During active development, aim for a stable checkpoint every 30–60 minutes. Push the latest checkpoint before switching tasks or ending a session, and verify the result with `git status -sb`. A checkpoint that preserves unfinished work should be labeled WIP.

## License

Apache License 2.0
