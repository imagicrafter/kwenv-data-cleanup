'use strict';

const express   = require('express');
const basicAuth = require('express-basic-auth');
const path      = require('path');

const app  = express();
const port = process.env.PORT || 8080;

const username = process.env.APP_USERNAME;
const password = process.env.APP_PASSWORD;

if (!username || !password) {
  console.error('ERROR: APP_USERNAME and APP_PASSWORD environment variables must be set');
  process.exit(1);
}

app.use(basicAuth({
  users: { [username]: password },
  challenge: true,
  realm: 'KW Environmental Data Cleanup',
}));

// Serve the self-contained offline build
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, 'KW_DataCleanup.html'));
});

// Health check for DO platform
app.get('/health', (req, res) => {
  res.sendStatus(200);
});

app.listen(port, () => {
  console.log(`KW Data Cleanup running on port ${port}`);
});
