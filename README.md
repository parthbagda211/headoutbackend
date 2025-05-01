# 🌍 Travel Game Flask Backend

This is a Flask backend for a travel trivia game. Users can register, get game questions based on clues, guess answers, and invite friends.

---

## 📦 Features

- User registration and score tracking
- Game session handling with scoring logic
- Invite system
- Fun travel facts and clues
- PostgreSQL + SQLAlchemy ORM
- RESTful API endpoints
- CORS support for frontend integration

---

## 🚀 Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/parthbagda211/headoutbackend.git
cd headoutbackend
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```
 
---

# User Table

The `User` table stores information about registered users, including their unique username and cumulative score.

## Columns

| Column     | Type   | Description                       |
|------------|--------|-----------------------------------|
| `id`       | UUID   | Primary key                       |
| `username` | String | Unique username                   |
| `score`    | Int    | Cumulative score of the user      |

## Example Schema

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(80) UNIQUE NOT NULL,
    score INT DEFAULT 0
);

```
---
# GameSession Table

The `GameSession` table tracks individual game attempts per question for each user.

## Columns

| Column       | Type    | Description                                   |
|--------------|---------|-----------------------------------------------|
| `id`         | UUID    | Primary key                                   |
| `user_id`    | FK      | Foreign key referencing the `User` table      |
| `correct`    | Boolean | Indicates whether the guess was correct       |
| `timestamp`  | DateTime| Timestamp of when the attempt was made        |
| `answer_id`  | Int     | Index of the correct answer from the JSON data|

## Example Schema

```sql
CREATE TABLE game_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id),
    correct BOOLEAN NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    answer_id INT NOT NULL
);

```
---

# Invite Table

The `Invite` table stores invite links from one user to another.

## Columns

| Column            | Type    | Description                                   |
|-------------------|---------|-----------------------------------------------|
| `id`              | UUID    | Primary key                                   |
| `inviter_id`      | UUID    | Foreign key referencing the `User` table      |
| `invitee_username`| String  | Username of the user who joined using the invite |
| `created_at`      | DateTime| Timestamp of when the invite was created     |

## Example Schema

```sql
CREATE TABLE invites (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    inviter_id UUID REFERENCES users(id),
    invitee_username VARCHAR(80),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
