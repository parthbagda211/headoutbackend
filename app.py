from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime
import uuid
import random
import json
import redis
import os
from dotenv import load_dotenv

app = Flask(__name__)
CORS(app, resources={r"*": {"origins": "*"}})

# --- PostgreSQL Setup ---
load_dotenv('.env')

USER_NAME = os.getenv('POSTGRES_USER')
PASSWORD = os.getenv('POSTGRES_PASSWORD')
HOST = os.getenv('POSTGRES_HOST')
PORT = os.getenv('POSTGRES_PORT', '5432')  # Default to 5432 if not set
DATABASE = os.getenv('POSTGRES_DB')

# Ensure all required environment variables are set
if not all([USER_NAME, PASSWORD, HOST, DATABASE]):
    raise EnvironmentError("One or more required PostgreSQL environment variables are missing: "
                           "POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_DB")


app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://{USER_NAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- Redis Setup ---
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_DB = int(os.getenv('REDIS_DB', 0))

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username = db.Column(db.String(50), unique=True, nullable=False)
    score = db.Column(db.Integer, default=0)

class GameSession(db.Model):
    id = db.Column(db.String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String, db.ForeignKey('user.id'))
    correct = db.Column(db.Boolean)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    answer_id = db.Column(db.Integer) # This is the index of the correct destination

class Invite(db.Model):
    id = db.Column(db.String, primary_key=True, default=lambda: str(uuid.uuid4()))
    inviter_id = db.Column(db.String, db.ForeignKey('user.id'), nullable=False)
    invitee_username = db.Column(db.String, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# --- Load Destinations ---
with open('data/final-travel-data.json') as f:
    DESTINATIONS = json.load(f)

# --- Routes ---


@app.route('/api/user', methods=['POST'])
def create_or_register_user():
    data = request.get_json()
    username = data.get('username')
    invite_id = data.get('invite_id')

    if not username:
        return jsonify({'error': 'Username is required'}), 400

    # Try to find existing user
    user = User.query.filter_by(username=username).first()

    if not user:
        # Create new user if not found
        user = User(username=username)
        db.session.add(user)
        db.session.flush()  # Get user.id without committing yet

        # If invite ID provided, update the invite
        if invite_id:
            invite = Invite.query.filter_by(id=invite_id).first()
            if invite:
                invite.invitee_username = username

    db.session.commit()

    return jsonify({
        'user_id': user.id,
        'username': user.username,
        'score': user.score
    }), 201


@app.route('/api/user/<username>', methods=['GET'])
def get_user(username):
    user = User.query.filter_by(username=username).first()
    if user:
        return jsonify({'username': user.username, 'score': user.score})
    return jsonify({'error': 'User not found'}), 404

@app.route('/api/game/question', methods=['GET'])
def get_question():
    destination = random.choice(DESTINATIONS)
    clues = random.sample(destination['clues'], k=2)
    options = random.sample([d['city'] for d in DESTINATIONS if d != destination], k=3)
    options.append(destination['city'])
    random.shuffle(options)
    return jsonify({
        'clues': clues,
        'options': options,
        'answer_id': DESTINATIONS.index(destination)  # For server-side check only
    })

@app.route('/api/game/guess', methods=['POST'])
def check_guess():
    data = request.get_json()
    selected = data.get('selected')
    answer = data.get('answer')  # index of correct destination
    user_id = data.get('user_id')

    destination = DESTINATIONS[answer]
    correct = selected == destination['city']
    fun_fact = random.choice(destination['fun_fact'])

    # Use Redis key to track if user already answered this question
    redis_key = f"session:{user_id}:{answer}"
    if redis_client.exists(redis_key):
        was_correct = redis_client.hget(redis_key, "correct") == 'True'
        return jsonify({
            'correct': correct,
            'fun_fact': fun_fact,
            'updated_score': User.query.get(user_id).score,
            'already_answered': True,
            'extra_clue': destination['clues'][1] if not was_correct else None
        })

    # Save to Redis (expire in 1 hour, optional)
    redis_client.hset(redis_key, mapping={"correct": str(correct), "timestamp": datetime.utcnow().isoformat()})
    redis_client.expire(redis_key, 3600)  # Expires in 1 hour

    # Save to PostgreSQL
    user = User.query.get(user_id)
    session = GameSession(user_id=user_id, correct=correct, answer_id=answer)
    db.session.add(session)
    

    if correct:
        user.score += 1
    # Store the updated score in Redis with a 20-minute expiration
    redis_client.setex(f"user:{user_id}:score", 1200, user.score)

    # Schedule a task to update the database after 20 minutes
    redis_key_db_update = f"user:{user_id}:db_update"
    if not redis_client.exists(redis_key_db_update):
        redis_client.setex(redis_key_db_update, 1200, "pending")

        def update_db_score():
            with app.app_context():
                user = User.query.get(user_id)
                if user:
                    cached_score = redis_client.get(f"user:{user_id}:score")
                    if cached_score is not None:
                        user.score = int(cached_score)
                        db.session.commit()

       
    return jsonify({
        'correct': correct,
        'fun_fact': fun_fact,
        'updated_score': user.score,
        'already_answered': False,
        'extra_clue': destination['clues'][1] if not correct else None
    })



@app.route('/api/invite', methods=['POST'])
def create_invite():
    data = request.get_json()
    inviter_id = data.get('inviter_id')
    invite = Invite(inviter_id=inviter_id)
    db.session.add(invite)
    db.session.commit()
    return jsonify({'invite_id': invite.id})

@app.route('/api/invite/<invite_id>', methods=['GET'])
def get_invite(invite_id):
    invite = Invite.query.get(invite_id)
    if not invite:
        return jsonify({'error': 'Invalid invite ID'}), 404
    inviter = User.query.get(invite.inviter_id)
    return jsonify({'inviter_username': inviter.username, 'score': inviter.score})


@app.route('/api/game/scores/<string:user_id>', methods=['GET'])
def get_scores(user_id):
    # First, try to fetch the score from Redis
    cached_score = redis_client.get(f"user:{user_id}:score")
    if cached_score is not None:
        cached_score = int(cached_score)
    else:
        # If not found in Redis, fetch from the database
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        cached_score = user.score
        # Cache the score in Redis for future requests
        redis_client.set(f"user:{user_id}:score", cached_score)

    # Calculate the current session score from the GameSession model
    current_score = GameSession.query.filter_by(user_id=user_id, correct=True).count()

    return jsonify({
        'total_score': cached_score,  # Total score (cached or fetched from DB)
        'current_score': current_score  # Score for the current session (correct answers)
    })

# --- Init DB ---
with app.app_context():
    db.create_all()

# --- Run Server ---
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5050))
    app.run(debug=True, host='0.0.0.0', port=port)
