#\!/bin/bash
cd /opt/dreamweaver-backend || exit 1

# Check if blog files have changed
git diff --quiet data/blog_posts.json data/blog_comments.json 2>/dev/null
if [ $? -ne 0 ]; then
    git add data/blog_posts.json data/blog_comments.json
    git commit -m "backup: blog data $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    git push origin main 2>/dev/null
fi
