DROP DATABASE IF EXISTS studyWithABuddyDB;
CREATE DATABASE studyWithABuddyDB;
USE studyWithABuddyDB;

CREATE TABLE users (
    user_id         INT           AUTO_INCREMENT PRIMARY KEY,
    user_name       VARCHAR(50)   UNIQUE NOT NULL,
    user_password   VARCHAR(255)  NOT NULL,
    user_rating     DECIMAL(3,2)  DEFAULT 0.00,
    rating_count    INT           DEFAULT 0,
    user_email      VARCHAR(100)  UNIQUE NOT NULL,
    is_verified     BOOLEAN       DEFAULT FALSE,
    avatar_id       INT           DEFAULT 0,
    #new fields for the purpose of reporting 
    account_status  ENUM('active','suspended','banned') NOT NULL DEFAULT 'active',
    suspension_days INT NOT NULL DEFAULT 0
);

CREATE TABLE slots (
    slot_id          INT           AUTO_INCREMENT PRIMARY KEY,
    owner_id         INT           NOT NULL,
    subject_name     VARCHAR(50)   NOT NULL,
    general_location VARCHAR(100)  NOT NULL,
    precise_location VARCHAR(100)  NOT NULL,
    remaining_time   INT,
    slot_type        ENUM('buddy','tutor') DEFAULT 'buddy',
    created_at       DATETIME      DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE slot_topics (
    topic_id INT          AUTO_INCREMENT PRIMARY KEY,
    slot_id  INT          NOT NULL,
    topic    VARCHAR(100) NOT NULL,
    FOREIGN KEY (slot_id) REFERENCES slots(slot_id) ON DELETE CASCADE
);

CREATE TABLE slot_requests (
    request_id   INT      AUTO_INCREMENT PRIMARY KEY,
    slot_id      INT      NOT NULL,
    requester_id INT      NOT NULL,
    status       ENUM('pending','accepted','rejected') DEFAULT 'pending',
    requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (slot_id)      REFERENCES slots(slot_id)  ON DELETE CASCADE,
    FOREIGN KEY (requester_id) REFERENCES users(user_id)  ON DELETE CASCADE,
    UNIQUE KEY unique_request (slot_id, requester_id)
);

CREATE TABLE notifications (
    notif_id   INT          AUTO_INCREMENT PRIMARY KEY,
    user_id    INT          NOT NULL,
    message    VARCHAR(500) NOT NULL,
    notif_type ENUM('request_accepted','request_rejected',
                    'session_ended','general') DEFAULT 'general',
    is_read    BOOLEAN  DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE user_ratings (
    rating_id  INT  AUTO_INCREMENT PRIMARY KEY,
    rater_id   INT  NOT NULL,
    rated_id   INT  NOT NULL,
    rating     INT  NOT NULL CHECK (rating BETWEEN 1 AND 5),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (rater_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (rated_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE KEY unique_rating (rater_id, rated_id)
);

CREATE TABLE reports (
    report_id     INT  AUTO_INCREMENT PRIMARY KEY,
    reporter_id   INT  NOT NULL,
    reported_id   INT  NOT NULL,
    reason        ENUM('Harassment','No Show','Spammer','Other') NOT NULL,
    to_university BOOLEAN  DEFAULT FALSE,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (reporter_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (reported_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE friends (
    friendship_id INT  AUTO_INCREMENT PRIMARY KEY,
    user_id_1     INT  NOT NULL,
    user_id_2     INT  NOT NULL,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id_1) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id_2) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE KEY unique_friendship (user_id_1, user_id_2)
);

CREATE TABLE IF NOT EXISTS anim_events (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    user_id    INT NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX (user_id)
);
