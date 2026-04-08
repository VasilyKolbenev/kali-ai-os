# Saving Features + No-Code Agent Builder Design

## Overview

Add features that help users save time and money, plus a no-code agent builder that lets anyone create custom agents by describing them in natural language.

## Saving Features

### 1. Morning Briefing
- Triggered by `schedule.morning` event
- Collects data from all agents: calendar (today's events), tasks (pending), weather (current), life-dashboard (budget status)
- Delivers via TTS + Telegram notification
- Format: short, spoken-friendly summary

### 2. Quick Capture (Smart Router)
- User says one phrase, LLM auto-routes to the right agent
- "купить молоко" → tasks.add_task
- "встреча завтра в 15:00" → calendar.create_event
- "потратил 1500 на еду" → life-dashboard.log_spending
- Uses LLM function calling — no keyword matching

### 3. Budget Goals
- Categories with spending limits (food: $500, transport: $200)
- Each log_spending checks against limits
- Warnings at 80% and 100%
- Weekly spending report by category

### 4. Subscription Tracker
- Analyzes spending patterns over 3 months
- Detects recurring amounts on similar dates
- Reports total subscription cost
- Flags unused subscriptions

### 5. Focus Timer
- "Jarvis, work 25 minutes" starts a Pomodoro session
- Avatar changes to orange/focused state
- Notifications muted during session
- Completion sound + break suggestion
- Stats tracked per day/week

### 6. Routines
- Named sequences of agent actions
- "morning routine": briefing → dashboard → lights on
- "evening routine": day summary → nightstand → lights off
- Created via voice: "create routine 'work' that shows tasks and starts focus timer"
- Stored as JSON, executed sequentially

### 7. Weekly Review
- Sunday evening scheduled event
- Aggregates: tasks completed/total, spending vs budget, sleep average, focus sessions, email volume
- Delivered via TTS + Telegram

## No-Code Agent Builder

### Flow
1. User describes desired agent in natural language
2. Jarvis (Claude) asks 1-2 clarifying questions
3. Claude generates agent.py + manifest.yaml
4. Safety check (no dangerous operations)
5. User confirms → agent loaded into runtime
6. Agent runs on schedule or on-demand

### Technical
- Claude generates Python inheriting BaseAgent
- Auto-creates manifest with tools, capabilities, schedule
- Validates: no file deletion, no arbitrary exec, no credential access
- Hot-loads into agent runtime without restart
- Stored in `agents/custom/` directory

### Community Sharing
- Export agent as zip (agent.py + manifest.yaml + README)
- Import from zip
- Future: community API/GitHub repo for sharing
- Rating system and usage stats (v2)

## Implementation Priority

1. Morning Briefing + Quick Capture (highest ROI)
2. Budget Goals + Focus Timer
3. Routines + Weekly Review + Subscription Tracker
4. No-Code Agent Builder
5. Community sharing (v2)
