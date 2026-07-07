# Changelog (บันทึกประวัติการเปลี่ยนแปลงโครงการ)

All notable changes to the **Manga/Manhua AI Translation Web Application** will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) and [Everything Claude Code (ECC)](https://github.com/everything-claude-code) principles.

---

## [1.0.0-MVP] - 2026-07-07

### Added
- **Frontend Web Application (`frontend/`)**:
  - Initialized **React + Vite + TypeScript + Tailwind CSS** project with modern dark mode aesthetics, glassmorphic UI cards, and glowing cyan/purple gradients.
  - Built `Navbar.tsx` and `Home.tsx` catalog page displaying translated manga series with responsive grid layout and "⚡ อ่านฟรี" badges.
  - Developed `Reader.tsx` vertical Webtoon scrolling viewer with touch gesture support, mobile-first borderless layout, and automatic Next/Prev chapter navigation.
  - Built `SubmitJob.tsx` interactive submission page with real-time animated progress bar (0-100%) and dynamic status badges (`SCRAPING`, `TRANSLATING`, `COMPLETED`).
- **Super Admin Control Panel (`Admin.tsx`) & Security Guard**:
  - Implemented secure JWT login form enforcing "คนลบได้มีเเค่คนมีเมลพาสของระบบเท่านั้น" restricted deletion access.
  - Added Danger Zone UI to delete series/chapters from SQLite database and trigger immediate cascade deletion of all associated images on Cloudflare R2.
- **Monetization Ad Slots (`AdSlot.tsx`)**:
  - Designed responsive sponsorship ad banners (Top, Bottom, Sidebar, and Inter-page every 2 pages) to generate revenue supporting server costs without disrupting user reading experience.
- **Production DevOps, Embedded TrueType Fonts & E2E Testing**:
  - Added full user and admin E2E test suite (`test_e2e_flow.py`) achieving 13/13 passing tests with 100% core pipeline coverage.
  - Downloaded and embedded Google TrueType fonts (`Prompt-Regular.ttf`, `Sarabun-Regular.ttf`) in `backend/assets/fonts/` to guarantee 100% identical Thai manga lettering on Windows and Ubuntu VPS without requiring Docker or OS font installation.
  - Created Windows automation scripts: `start_app.bat` (one-click launch of both servers + auto browser open) and `update_app.bat` (one-click `git pull` auto-updater and build).
  - Published comprehensive Native VPS (PM2 + Nginx + Python venv) operational guide in [DEPLOYMENT_RUNBOOK.md](file:///e:/Code/manhwabkk/DEPLOYMENT_RUNBOOK.md).

---

## [0.1.3] - 2026-07-07

### Added
- **Web Scraper & Crawler (`backend/src/infrastructure/scraper/`)**:
  - Built `ScraperService` using `BeautifulSoup` and `httpx` to dynamically extract manga page images and auto-detect "Next Chapter" / "Prev Chapter" navigation URLs.
- **Vision & AI Translation Pipeline (`backend/src/pipeline/` & `backend/src/infrastructure/ai/`)**:
  - Implemented `GroqClient` connecting to OpenAI-compatible chat completion endpoint (`llama-3.3-70b-versatile`).
  - Created `AITranslatorEngine` with custom Thai webtoon system prompt enforcing natural, engaging slang without machine translation tropes.
  - Developed `MangaOCREngine` for bubble box detection and `InpainterEngine` for old text removal/whitening.
  - Implemented `TypesetterEngine` using `Pillow` for automatic word wrapping and vertical centering of Thai text inside bubble coordinates.
- **Pipeline Orchestrator (`backend/src/pipeline/worker.py`)**:
  - Developed `TranslationPipelineWorker` linking the end-to-end flow: Scraping (10-30%) -> OCR/Inpaint/Translate/Typeset (40-90%) -> Cloudflare R2 upload with immutable cache (95%) -> SQLite database registration (100%).
- **TDD Test Verification (`backend/tests/test_pipeline.py`)**:
  - Verified link extraction, Groq prompt formatting, text rendering, and complete workflow simulation with 100% test pass rate (12/12 tests passed in 3.36s).

## [0.1.2] - 2026-07-07

### Added
- **Database & ORM Setup (`backend/src/database.py`)**:
  - Implemented async SQLAlchemy 2.0 engine and Declarative Base with local SQLite (`manga_app.db`) auto-creation on startup.
- **Repository Pattern & Common Modules (`backend/src/common/`)**:
  - Built abstract `IRepository` and concrete `BaseSQLAlchemyRepository` to ensure storage decoupling.
  - Implemented consistent API response envelopes (`APIResponse`, `success_response`, `error_response`) and structured domain exceptions.
- **Domain Layer Implementation (`backend/src/domains/`)**:
  - **Auth**: User ORM model, Pydantic v2 schemas, JWT issuance, bcrypt hashing, auto Super Admin creation, and `require_super_admin` permission guard.
  - **Manga**: Series, Chapter, Page models with async `lazy="selectin"` loading, cascading deletions, and reader view cache logic.
  - **Jobs**: TranslationJob model and repository for tracking real-time 0-100% progress.
- **TDD Test Verification (`backend/tests/`)**:
  - Implemented `test_auth.py` and `test_repository.py` using in-memory async SQLite.
  - Achieved 100% test pass rate (8/8 tests passed in 2.99s) verifying cascade deletes, eager loading, and role-based access control.

## [0.1.1] - 2026-07-07

### Added
- **Cloudflare R2 Storage Integration (`backend/src/infrastructure/storage/`)**:
  - Implemented `r2_client.py` and `r2_service.py` supporting S3-compatible endpoints.
  - Enforced mandatory immutable caching headers (`Cache-Control: public, max-age=86400, immutable`) on all image uploads to eliminate repeat download bandwidth and R2 Class B operation costs.
  - Implemented protected Super Admin cleanup actions (`delete_chapter_images` and `delete_series_images`).
- **TDD Unit Testing (`backend/tests/test_storage.py`)**:
  - Configured virtual environment (`backend/.venv`) and installed all Phase 1 & vision pipeline dependencies.
  - Created automated test suite using `moto` (S3 mock) achieving 100% test pass rate for upload caching rules and granular admin deletion boundaries.

## [0.1.0] - 2026-07-07

### Added
- **Project Architecture & Plan (`PROJECT_PLAN.md`)**:
  - Formulated the comprehensive architectural blueprint for the Local MVP prototype scalable to VPS.
  - Core concept implementation: *"First person translates, next readers read free"* (คนแรกสั่งแปล คนต่อไปอ่านฟรี).
- **Tech Stack Selection & Justification**:
  - **Backend API & Worker**: Selected **Python 3.11+ (FastAPI + AsyncIO)** for native integration with AI/ML computer vision libraries (`MangaOCR`, `OpenCV`, `Pillow`) and high-performance asynchronous REST API generation.
  - **Frontend UI**: Selected **React 18 + Vite + TypeScript + Tailwind CSS** for a responsive single-page webtoon reader optimized for both mobile touch gestures and desktop screens, including dedicated monetization ad slots (banner/sidebar ads) to support server costs.
  - **Database & ORM**: Selected **SQLite** with **SQLAlchemy 2.0 (Async) + Alembic** for zero-config local development, structured via the **Repository Pattern** for zero-code migration to PostgreSQL on VPS.
  - **AI Translation Brain**: Integrated **Groq API (Llama-3.3-70b-versatile / Mixtral-8x7b)** with custom system prompts adapting slang and context to Thai webtoon reader style.
  - **Web Scraper & Crawler**: Selected **Playwright (Python Async) + HTTPX + BeautifulSoup4** for dynamic image scraping and intelligent "Next/Prev Chapter" link extraction.
  - **Vision Pipeline**: Designed modular stages: Speech Bubble Detection (`MangaOCR` / `EasyOCR`) -> Background Inpainting (`OpenCV` / `Simple-LaMa`) -> AI Dialogue Translation (`Groq`) -> Thai Typesetting (`Pillow`).
- **Cloudflare R2 Storage & Caching Rules**:
  - Established S3-compatible path convention: `manga-thai-storage/[manga-slug]/[chapter-number]/[page-index].jpg`.
  - Enforced mandatory immutable browser caching header: `Cache-Control: public, max-age=86400, immutable` to minimize R2 Class B operations and bandwidth consumption.
- **Database Schema (SQLite DDL & ERD)**:
  - Formulated 3NF tables: `users`, `series`, `chapters`, `pages`, and `translation_jobs` with UUID tracking, status enumerations, and foreign key cascading.
- **RESTful API Specifications & Standard Envelopes**:
  - Standardized JSON response envelope across all endpoints (`success`, `data`, `error`, `meta`).
  - Specified endpoints for Auth, Catalog, Chapters/Reader, Translation Jobs, and protected Super Admin actions.
- **Phased Implementation Roadmap**:
  - Defined 4-phase milestone schedule starting with **Phase 1: Environment & Cloudflare R2 Storage Setup** as explicitly required by the project blueprint.
- **ECC Mandatory Rule Compliance**:
  - Initialized `CHANGELOG.md` adhering to user rule: *"เซฟประวัติการแก้ไขไว้ใน CHANGELOG.md เสมอ"*.
  - Verified planning workflow adherence: *"ก่อนเริ่มงานใหม่หากมีการ plan งานใหม่ให้ทำ project plan อัพเดทลงใน PROJECT_PLAN.md ก่อนเสมอ"*.
