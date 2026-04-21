# Resume Generation Rules & Guidelines

## Core Principles

### 1. Never Make Up Information
- Only use content from your candidate database
- Don't fabricate technologies, skills, or experiences
- Be honest about experience gaps and skill levels
- Use qualifiers like "learning" or "exposure to" when appropriate

### 2. Keep It Natural and Concise
- Avoid marketing language and excessive adjectives
- Write in clear, direct language
- Keep bullets focused and impactful
- Let metrics and facts speak for themselves

### 3. Maintain Accuracy
- Use actual job titles from experience
- Include real metrics only
- Don't exaggerate or inflate roles
- Be truthful about project scope

---

## Resume Generation Process

### Step 1: Analyze the Job Description

**Extract Key Information:**
1. **Top 3-5 Required Skills** - Identify must-have technical skills
2. **Core Responsibilities** - What will you actually do day-to-day
3. **Keywords** - Technologies, methodologies, tools mentioned
4. **Experience Level** - Years required, seniority expectations
5. **Dealbreakers** - Visa requirements, location, citizenship, etc.

**Flag Critical Blockers:**
- U.S. Citizenship required
- Visa sponsorship not available
- Specific location with in-office requirements

### Step 2: Map Candidate Skills to JD

**Priority Matching:**
1. **Exact Matches** - Skills candidate has that JD requires
2. **Transferable Skills** - Related experience that applies
3. **Learning Gaps** - Skills candidate can acquire quickly
4. **Hard Gaps** - Missing expertise that takes years to build

### Step 3: Rewrite Bullet Points

**Bullet Point Formula:**
```
[Action Verb] + [What You Did] + [Technology/Method] + [Quantifiable Result]
```

**Strong Action Verbs:**
- **Building:** Architected, Engineered, Developed, Implemented, Built, Designed
- **Improving:** Optimized, Reduced, Enhanced, Streamlined, Accelerated
- **Leading:** Led, Spearheaded, Drove, Championed, Directed
- **Analyzing:** Analyzed, Identified, Evaluated, Assessed
- **Collaborating:** Collaborated, Partnered, Coordinated, Facilitated

**Keyword Integration:**
- Use exact terms from JD when they match actual experience
- Example: JD says "Kubernetes" -> Use "Kubernetes" not "container orchestration"

**Quantification Rules:**
- Use actual metrics from candidate database
- Never inflate numbers
- If no metric exists, describe scope instead (e.g., "40+ microservices")

### Step 4: Structure the Resume

#### A. Professional Summary (3 lines max)
- Mirror JD's role title when appropriate
- Lead with skills most relevant to JD
- Include domain experience if JD is industry-specific

#### B. Skills Section
**Ordering:** JD-required skills first, then related, then additional
**Max 4-5 categories**, combine related ones

#### C. Experience Section
- First 3-4 bullets: Most relevant to JD (use their keywords)
- Middle bullets: Supporting technical achievements
- Last bullets: Collaboration, mentorship, process improvements
- Max 1-2 lines per bullet; past tense for previous roles

#### D. Projects Section
- Pick 3-4 most relevant projects to the JD
- Order by relevance to role, not chronologically
- 3-5 bullets per project
- Don't oversell hackathon projects as production systems

#### E. Education & Extracurricular
- Pick courses that align with JD requirements
- 2-3 extracurricular bullets max
- Only include if demonstrates relevant skills

#### F. ATS Scoring
- Target 90+ ATS score
- If below 90, iterate and improve keyword coverage

---

## Output Format

### YAML Structure
```yaml
name: [Your Name]
contact:
  location: [City, State]
  phone: [Phone]
  email: [Email]
  github: [GitHub URL]
  linkedin: [LinkedIn URL]

summary: [3-line tailored summary]

education:
- institution: [School Name]
  location: [City, State]
  degree: [Degree]
  gpa: '[GPA]'
  date: [Graduation Date]
  coursework: [1-3 most relevant courses]

technical_skills:
- category: [JD-relevant category name]
  skills: [Comma-separated skills, JD keywords first]

experience:
- company: [Company Name]
  role: [Actual title matching JD focus]
  location: [Location]
  date: [Start] - [End]
  bullets:
  - [Bullets prioritized by JD relevance]

projects:
- name: [Project Name]
  event: [Event/Type]
  date: [Date]
  bullets:
  - [3-5 bullets]

extracurricular:
  bullets:
  - [2-3 leadership/community bullets]
```

### Assessment Comments (after YAML)
```
### Honest Assessment:
What You Actually Have: [matches]
Experience Gaps: [missing skills]
```

---

## Content Guidelines

### What to Include
- Actual quantified achievements from candidate database
- Specific technologies used (not generic descriptions)
- Scope of work (number of services, users, systems)
- Collaboration and cross-functional work

### What to Avoid
- Made-up technologies or skills
- Inflated metrics or achievements
- Generic buzzwords without substance
- Responsibilities not actually performed
- Em dashes (use semicolons, commas, colons instead)
- Excessive adjectives like "robust", "cutting-edge", "world-class"
- Vague phrases like "worked on" or "helped with"

---

## Quality Checklist

- All information is from candidate database
- No fabricated skills or experiences
- Metrics are actual, not inflated
- Job titles match actual roles
- Bullet points use JD keywords where accurate
- Action verbs start each bullet
- Quantification included where possible
- Skills ordered by JD priority
- Most relevant projects highlighted
- Natural, concise language throughout
- No em dashes anywhere
- Critical blockers flagged if present
