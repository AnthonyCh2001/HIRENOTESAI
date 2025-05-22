drop database db_poo;

create database db_poo;

use db_poo;

CREATE TABLE usuario (
  id int(5) NOT NULL primary key auto_increment,
  nombre varchar(50) NOT NULL,
  telefono varchar(50) NOT NULL,
  email varchar(50) NOT NULL
) ENGINE=InnoDB AUTO_INCREMENT=100 DEFAULT CHARSET=latin1;

insert into usuario(nombre,telefono,email)
values ('Jaime','999888777','jaime@abc.com');
