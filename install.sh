#!/bin/bash

echo "=================================="
echo "     OTT Admin Panel Installer    "
echo "=================================="

# Update system
sudo apt update && sudo apt upgrade -y

# Install Node.js, npm, and MongoDB
sudo apt install -y nodejs npm mongodb

# Create project folder
mkdir -p ~/ott-admin-panel/backend ~/ott-admin-panel/frontend
cd ~/ott-admin-panel

# Initialize Node.js project
cd backend
npm init -y
npm install express mongoose cors body-parser

# Create backend server.js
cat <<EOF > server.js
const express = require("express");
const mongoose = require("mongoose");
const bodyParser = require("body-parser");
const cors = require("cors");
const app = express();
const PORT = 5000;

app.use(cors());
app.use(bodyParser.json());
app.use(express.static("../frontend"));

mongoose.connect("mongodb://localhost:27017/ott", {
  useNewUrlParser: true,
  useUnifiedTopology: true,
});

const Movie = mongoose.model("Movie", {
  title: String,
  description: String,
  poster: String,
  videoLink: String,
});

app.get("/api/movies", async (req, res) => {
  const movies = await Movie.find();
  res.json(movies);
});

app.post("/api/movies", async (req, res) => {
  const movie = new Movie(req.body);
  await movie.save();
  res.json(movie);
});

app.delete("/api/movies/:id", async (req, res) => {
  await Movie.findByIdAndDelete(req.params.id);
  res.sendStatus(204);
});

app.listen(PORT, () => {
  console.log(\`🎬 OTT backend running at http://localhost:\${PORT}\`);
});
EOF

# Create frontend files
cd ../frontend

# admin.html
cat <<EOF > admin.html
<!DOCTYPE html>
<html>
<head><title>OTT Admin Panel</title></head>
<body>
  <h2>Add Movie</h2>
  <form id="movieForm">
    <input type="text" id="title" placeholder="Title" required /><br />
    <textarea id="description" placeholder="Description"></textarea><br />
    <input type="text" id="poster" placeholder="Poster URL" required /><br />
    <input type="text" id="videoLink" placeholder="Video Link (MP4/M3U8)" required /><br />
    <button type="submit">Add Movie</button>
  </form>

  <h3>Movie List</h3>
  <ul id="movieList"></ul>

  <script>
    async function fetchMovies() {
      const res = await fetch("/api/movies");
      const movies = await res.json();
      const list = document.getElementById("movieList");
      list.innerHTML = "";
      movies.forEach(movie => {
        const li = document.createElement("li");
        li.textContent = movie.title + " | ";
        const del = document.createElement("button");
        del.textContent = "Delete";
        del.onclick = async () => {
          await fetch(\`/api/movies/\${movie._id}\`, { method: "DELETE" });
          fetchMovies();
        };
        li.appendChild(del);
        list.appendChild(li);
      });
    }

    document.getElementById("movieForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = {
        title: document.getElementById("title").value,
        description: document.getElementById("description").value,
        poster: document.getElementById("poster").value,
        videoLink: document.getElementById("videoLink").value,
      };
      await fetch("/api/movies", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      fetchMovies();
    });

    fetchMovies();
  </script>
</body>
</html>
EOF

# index.html (viewer)
cat <<EOF > index.html
<!DOCTYPE html>
<html>
<head><title>Watch Movies</title></head>
<body>
  <h1>Available Movies</h1>
  <div id="movies"></div>

  <script>
    fetch("/api/movies")
      .then(res => res.json())
      .then(movies => {
        const container = document.getElementById("movies");
        movies.forEach(movie => {
          const div = document.createElement("div");
          div.innerHTML = \`
            <h3>\${movie.title}</h3>
            <img src="\${movie.poster}" alt="poster" width="150" /><br/>
            <video width="320" controls>
              <source src="\${movie.videoLink}" type="video/mp4">
              Your browser does not support the video tag.
            </video>
            <hr/>\`;
          container.appendChild(div);
        });
      });
  </script>
</body>
</html>
EOF

# Return to project root and instructions
cd ~/ott-admin-panel

echo "=========================================="
echo "✅ OTT Panel Installed Successfully!"
echo "To run the server, execute:"
echo "cd ~/ott-admin-panel/backend && node server.js"
echo
echo "Then visit:"
echo "Admin Panel: http://<your-raspberry-pi-ip>:5000/admin.html"
echo "Movie Viewer: http://<your-raspberry-pi-ip>:5000/index.html"
echo "=========================================="
