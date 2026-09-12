---
name: habit-gamification
description: Habit streaks, celebrations, adaptive difficulty, habit stacking, reward system
---

# Habit Gamification Skill

Transforms habit tracking from chore to game. Builds on habit-tracker skill with motivational mechanics.

## Features

### Streak Tracking
- Current streak count
- Longest streak record
- Streak freeze (skip without breaking streak)

### Adaptive Difficulty
- If 3 consecutive misses: suggest lower target
- If 7-day streak: increase target by 10%
- If 30-day streak: celebrate + unlock achievement

### Habit Stacking
- Suggest new habits to attach to existing streaks
- Morning/evening routine optimization

### Rewards
- Points for completion (1pt per habit)
- Bonus for streak milestones (7: +5, 30: +15, 100: +50)
- Weekly leaderboard (self only)

## Commands

```bash
# Check in a habit
python3 ~/.hermes/skills/habit-gamification/check.py <habit_id>

# Get streak status
python3 ~/.hermes/skills/habit-gamification/streaks.py --habit <id>

# Adaptive suggestions
python3 ~/.hermes/skills/habit-gamification/adapt.py

# Habit stacking suggestions
python3 ~/.hermes/skills/habit-gamification/stack.py <existing_habit_id>
```

## Integration

- Reads from `~/.hermes/habits/habits.json`
- Updates points to `~/.hermes/habits/points.json`
- Telegram notifications for celebrations

## Achievement Badges

| Badge | Criteria | Reward |
|-------|----------|--------|
| 🔥 7-day fire | 7 consecutive days | +5 pts |
| 🔥🔥 30-day inferno | 30 consecutive days | +15 pts |
| 💎 Diamond | 100 consecutive days | +50 pts |
| 📈 Improvement | Consistently hit target for 14d | +10 pts |
| 🔄 Comeback | Return after 2+ missed days | +5 pts |