# Coachy AI Backend

<!-- Insert 4-5 relevant professional badges here. Mimic this style: -->
[![Version](https://img.shields.io/badge/Version-0.1.0-blue.svg)]()
[![Tech Stack](https://img.shields.io/badge/Tech-FastAPI%20%7C%20PostgreSQL%20%7C%20Redis-blue.svg)]()
[![License: Proprietary](https://img.shields.io/badge/License-Proprietary-yellow.svg)](LICENSE)
[![Hackathon](https://img.shields.io/badge/Hackathon-Build__with__AI-ff69b4.svg)](https://ai.gdgtashkent.uz/hackathon)

## Overview

The Coachy AI Backend serves as the highly scalable and real-time core for the CoachAI / Coachy AI.Uz platform, specifically designed to help students prepare for the BMBA Milliy Sertifikat exams. Built on a modern async stack, it orchestrates complex data flows, manages AI-driven personalized learning paths, and powers competitive multiplayer experiences for students across the region. 

It connects deeply integrated AI tutoring capabilities (via Google Gemini) with real-time websocket and Server-Sent Events (SSE) architectures to provide instant, dynamic feedback and engagement. This backend engine not only powers diagnostic exams and graded assessments but also generates evolving learning roadmaps and supports live, ranked battles to gamify the learning experience.

## Features & Functionality

- **AI-Powered Tutoring Engine:** Seamless integration with Google Gemini 2.0 via Server-Sent Events (SSE) to deliver step-by-step interactive math and science coaching, helping students overcome roadblocks dynamically.
- **Real-Time Multiplayer Battles:** Live, ranked student-vs-student and student-vs-AI battles driven by WebSockets. Features match-making, ELO ratings, and rapid question dispatching.
- **Adaptive Mock Exams & Grading:** Comprehensive mock exam sessions covering diverse subjects. Built-in grading algorithms provide precise Rasch scoring, deep topic-by-topic analytics, and performance summaries.
- **Dynamic Learning Roadmaps:** Generates adaptive, multi-week study milestones tailored to a student's performance on diagnostic exams, highlighting weak topics and tracking progressive mastery.
- **Robust Asynchronous Architecture:** Leverages FastAPI and asyncpg for high concurrency, backed by Redis and Celery for distributed background tasks such as premium expiry, snapshotting, and matchmaking cleanup.

## Getting Started

### Prerequisites

- Python 3.12+
- PostgreSQL 15+
- Redis (for Celery and state management)
- Docker & Docker Compose (optional, for easy infrastructure setup)

### Installation & Configuration

1. Clone the repository and navigate to this directory.
2. Copy the example environment file and configure your keys:
   ```bash
   cp .env.example .env
   ```
3. Install the dependencies:
   ```bash
   pip install -e .
   # or for development: pip install -e .[dev]
   ```
4. Run the development server:
   ```bash
   uvicorn app.main:app --reload
   ```

## Members
- **Muhammad Jabborov:** Team Member 1 - Backend Engineer
- **Sukhrob Tokhirov:** Team Member 2 - FrontEnd Engineer
- **Ali Sultonov:** Team Member 3 - AI/ML Englineer

## License
Proprietary — bwi-edtech-hackathon.
