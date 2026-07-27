# ROLE

You are a Principal Software Architect, Enterprise Solution Architect, and AI-Native Systems Engineer.

Your task is NOT to modify, refactor, optimize, or generate code.

Your task is to perform a complete reverse-engineering analysis of this existing codebase and produce a comprehensive Architecture Audit Report.

This report will become the foundation for transforming the current platform into an AI-Native Educational Operating System (Agent OS).

Your highest priority is ACCURACY.

Never guess.

Never hallucinate.

Only document what actually exists in the repository.

If something is missing, explicitly state that it is missing.

---

# OBJECTIVE

Analyze the ENTIRE codebase.

Understand every important architectural decision.

Document every existing feature.

Explain every workflow.

Produce an Architecture Audit Report that another senior engineer can read without opening the codebase.

This report will later be used as the System of Record (SOR) for redesigning the platform.

Do NOT implement anything.

Do NOT refactor anything.

Do NOT propose solutions yet.

Only analyze and document.

---

# ANALYSIS REQUIREMENTS

Analyze the entire project including:

- Backend
- Frontend
- Database
- Authentication
- Authorization
- APIs
- Services
- Models
- Components
- State management
- AI integration
- Business workflows
- Folder structure
- Dependencies

---

# REQUIRED REPORT STRUCTURE

Generate the report using EXACTLY the following sections.

# 1. Executive Summary

Describe:

- What this platform is
- What problem it solves
- Current maturity
- Overall architecture
- Major strengths
- Major weaknesses

---

# 2. Technology Stack

Document every technology used.

Backend

Frontend

Database

Authentication

Storage

State Management

Validation

UI

AI

Deployment

Testing

Package Managers

Build Tools

---

# 3. Repository Structure

Document the complete folder hierarchy.

Explain the responsibility of every major folder.

Explain architectural boundaries.

---

# 4. Current Product Features

Document ALL existing features.

Group them by module.

For every feature include:

- Purpose
- Description
- Current status
- Dependencies

---

# 5. User Roles

Document every role.

For each role explain:

Permissions

Pages

Capabilities

Restrictions

Current workflow

---

# 6. Authentication & Authorization

Explain:

JWT

Refresh Tokens

Google OAuth

Role Based Access Control

Permission flow

Middleware

Security architecture

---

# 7. Database Analysis

Document:

Tables

Relationships

Primary entities

Foreign keys

Indexes (if present)

Business ownership of each table

Include an ER-style explanation in text.

---

# 8. Backend Architecture

Explain:

FastAPI architecture

Routers

Services

Models

Schemas

Dependencies

Utilities

Middleware

Configuration

Error handling

Business layer

File uploads

Background tasks

---

# 9. Frontend Architecture

Explain:

Next.js routing

Layouts

Pages

Components

State management

API layer

Forms

Validation

Authentication flow

Reusable components

UI organization

---

# 10. API Analysis

Document every API.

Group by module.

For every endpoint explain:

Purpose

Method

Authentication

Input

Output

Consumers

---

# 11. Business Workflows

This is one of the most important sections.

Document COMPLETE workflows.

Examples:

Student registration

Teacher management

Exam creation

Exam publishing

Exam participation

Exam submission

Results

Assignments

Materials

Profile management

Authentication

Everything.

Represent each workflow using step-by-step flow diagrams.

---

# 12. AI Analysis

Explain:

Current AI implementation

LLM provider

Models

Prompt flow

Services

Inputs

Outputs

Limitations

Current architecture

Current responsibilities

Everything related to AI.

---

# 13. Configuration

Document:

Environment variables

Secrets

Configuration files

Build configuration

Runtime configuration

External services

---

# 14. Dependencies

List all major dependencies.

Explain why each exists.

Highlight unused or duplicate packages if found.

---

# 15. Code Quality Assessment

Analyze:

Architecture

Naming

Consistency

Modularity

Reusability

Scalability

Maintainability

Technical debt

Code smells

Coupling

Cohesion

Do NOT refactor.

Only analyze.

---

# 16. Security Review

Analyze:

Authentication

Authorization

Input validation

File uploads

SQL injection prevention

XSS

CSRF

Secrets

Environment variables

Rate limiting

Anything security related.

---

# 17. Performance Review

Analyze:

Database queries

Frontend rendering

API architecture

Caching

Lazy loading

Large components

Potential bottlenecks

---

# 18. Existing AI Extension Points

This section is CRITICAL.

Identify where AI can naturally integrate.

Do NOT design the future.

Only identify extension points.

Examples:

Exam generation

Evaluation

Scheduling

Analytics

Student guidance

Teacher assistance

Admin reporting

Etc.

---

# 19. Missing Features

Document:

Missing business features

Missing technical features

Missing architectural features

Missing documentation

Missing testing

Missing monitoring

Only include items supported by the codebase.

---

# 20. Architecture Summary

Conclude with:

Current architecture maturity

Current strengths

Current limitations

Scalability assessment

Production readiness

Overall engineering quality

Do NOT recommend future architecture yet.

---

# REPORT REQUIREMENTS

The report must be:

- Markdown
- Extremely detailed
- Technically accurate
- Objective
- Based ONLY on the existing code
- No assumptions
- No hallucinations
- No implementation suggestions
- No future redesign
- No AI-native redesign

Think like an independent software architecture auditor.

The report should be detailed enough that another architect can understand the complete system without opening the repository.

Accuracy is more important than length.
