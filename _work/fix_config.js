const fs=require('fs');
const p='C:/Users/13411/Desktop/software/frontend/src/App.vue';
let s=fs.readFileSync(p,'utf8');
s=s.replace("<template v-else-if=\"active='源储协同配置'\">","<template v-else-if=\"active==='源储协同配置'\">");
fs.writeFileSync(p,s);
