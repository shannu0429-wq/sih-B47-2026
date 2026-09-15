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

drop table users;



select * from users;

select * from notifications;

