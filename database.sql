create database smart_farm;

use smart_farm;

create table users (
    id int auto_increment primary key,
    fullname varchar(100) not null,
    email varchar(100) not null unique,
    mobile varchar(15) not null,
    username varchar(50) not null unique,
    password varchar(255) not null,
    created_at timestamp default current_timestamp
);

     CREATE TABLE IF NOT EXISTS notifications (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            animal VARCHAR(100) NOT NULL,
            confidence DECIMAL(5,2) NOT NULL,
            image VARCHAR(500),
            detected_at DATETIME NOT NULL,
            INDEX idx_user_id (user_id),
            INDEX idx_detected_at (detected_at)
        );
        
drop table users;
update users set password="Shanmukha@0429" where id=1;
select * from users;

select * from notifications;