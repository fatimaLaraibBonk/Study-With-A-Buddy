# 📚 StudyWithABuddy

**Find your study partner. Build better habits. Learn together.**

StudyWithABuddy is a Flask-based web application designed to help students connect with one another, organize study sessions, and build a collaborative learning environment.

Users can create study slots, discover other students' sessions, request to join, and track their academic collaboration through profiles, ratings, achievements, and completed-session statistics.

The platform also incorporates user reporting and automated moderation to encourage a safer and more accountable community.

---

## ✨ Features

### 1. User Authentication
- User registration and login.
- Email verification through verification codes.
- Password hashing using **Bcrypt**.
- Session-based authentication.
- Password changing and account deletion.

### 2. Study Session Management
- Create study slots by specifying:
  - Subject name
  - General location
  - Precise location
  - Topics being studied
  - Session duration
  - Session type
- Browse available study sessions.
- Request to join another student's session.
- Accept or decline incoming requests.
- Leave an accepted session.
- Delete your own study slots.

### 3. Session Tracking
- Automatic countdown for active study slots.
- Background worker that checks session expiration.
- Automatic closure of expired slots.
- Completed-session records.
- Participant tracking for session owners and accepted buddies.

### 4. User Profiles and Reputation
- Customizable avatars.
- Public user profiles.
- Average user ratings and rating counts.
- Study-session statistics, including:
  - Sessions hosted
  - Sessions joined
  - Total completed sessions
  - Total study hours
- Dynamic profile titles based on ratings and participation.

### 5. Achievements and Gamification

Users can unlock achievements through their participation in the platform.

| Achievement | Requirement |
|---|---|
| 🌱 First Step | Post your first study slot |
| 🤝 First Buddy | Join a study session |
| 📚 Study Group | Join five sessions |
| ⭐ Well Rated | Obtain a 4.0+ average rating with at least three ratings |
| 👥 Social Butterfly | Add three study buddies |
| 🏆 Elite Scholar | Complete 20 or more sessions |

Profile titles also reflect user activity and reputation, ranging from **Newcomer** to **Legendary Buddy**.

### 6. Study Buddies
- Add and remove other users
