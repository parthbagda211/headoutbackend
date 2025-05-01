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

db = SQLAlchemy(app)

# --- Redis Setup ---

REDIS_HOST = os.getenv('REDIS_HOST')
REDIS_PORT = os.getenv('REDIS_PORT')
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD')

if REDIS_PASSWORD:
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
else:
  r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

# --- Models ---

class User(db.Model):
    id = db.Column(db.String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username = db.Column(db.String(50), unique=True, nullable=False)
    score = db.Column(db.Integer, default=0)

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
def register_user():
    data = request.get_json()
    username = data.get('username')
    user = User.query.filter_by(username=username).first()
    if not user:
        user = User(username=username)
        db.session.add(user)
        db.session.commit()
    return jsonify({'username': user.username, 'score': user.score, 'user_id': user.id})

@app.route('/api/user/<username>', methods=['GET'])
def get_user(username):
    user = User.query.filter_by(username=username).first()
    if user:
        return jsonify({'username': user.username, 'score': user.score})
    return jsonify({'error': 'User not found'}), 404

@app.route('/api/game/question', methods=['GET'])
def get_question():
    destination = random.choice(DESTINATIONS)
    clues = random.sample(destination['clues'], k=1)
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
    answer = data.get('answer')
    user_id = data.get('user_id')

    destination = DESTINATIONS[answer]
    correct = selected == destination['city']
    fun_fact = random.choice(destination['fun_fact'])

    user = User.query.get(user_id)
    session_key = f"user:{user_id}:answered:{answer}"

    if r.exists(session_key):
        was_incorrect = r.get(session_key) == 'false'
        return jsonify({
            'correct': correct,
            'fun_fact': fun_fact,
            'updated_score': user.score,
            'already_answered': True,
            'extra_clue': destination['clues'][1] if was_incorrect and len(destination['clues']) > 1 else None
        })

    # Save session to Redis
    r.set(session_key, str(correct).lower(),ex=1800)  # 'true' or 'false'

    if correct:
        user.score += 1
    db.session.commit()

    return jsonify({
        'correct': correct,
        'fun_fact': fun_fact,
        'updated_score': user.score,
        'already_answered': False,
        'extra_clue': destination['clues'][1] if not correct and len(destination['clues']) > 1 else None
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
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Count correct answers in current Redis session
    pattern = f"user:{user_id}:answered:*"
    correct_count = 0
    for key in r.scan_iter(match=pattern):
        if r.get(key) == 'true':
            correct_count += 1

    return jsonify({
        'total_score': user.score,
        'current_score': correct_count
    })

# --- Init DB ---
with app.app_context():
    db.create_all()

# --- Run Server ---
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
