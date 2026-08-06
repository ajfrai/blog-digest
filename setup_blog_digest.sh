#!/bin/bash
# Setup script for Daily Blog Digest

echo "Setting up Daily Blog Digest..."

# Install required Python package
echo "Installing required Python packages..."
pip3 install feedparser --user

# Make the script executable
chmod +x ~/blog_digest.py

echo ""
echo "======================="
echo "EMAIL CONFIGURATION"
echo "======================="
echo ""
echo "You need to set up email credentials. For Gmail:"
echo "1. Enable 2-factor authentication on your Google account"
echo "2. Generate an App Password at: https://myaccount.google.com/apppasswords"
echo "3. Create a file with your credentials:"
echo ""
echo "Create ~/.blog_digest_env with:"
echo "export SMTP_SERVER='smtp.gmail.com'"
echo "export SMTP_PORT='587'"
echo "export SMTP_USER='your-email@gmail.com'"
echo "export SMTP_PASSWORD='your-app-password'"
echo ""
read -p "Press enter to continue..."

# Create a wrapper script that sources the env file
cat > ~/run_blog_digest.sh << 'EOF'
#!/bin/bash
# Load environment variables
if [ -f ~/.blog_digest_env ]; then
    source ~/.blog_digest_env
fi
# Run the script
python3 ~/blog_digest.py
EOF

chmod +x ~/run_blog_digest.sh

echo ""
echo "======================="
echo "CRON SETUP"
echo "======================="
echo ""
echo "Adding nightly cron job (runs at 8 AM daily)..."

# Add cron job if it doesn't exist
CRON_CMD="0 8 * * * ~/run_blog_digest.sh >> ~/blog_digest.log 2>&1"
(crontab -l 2>/dev/null | grep -v "run_blog_digest.sh"; echo "$CRON_CMD") | crontab -

echo ""
echo "Setup complete!"
echo ""
echo "Next steps:"
echo "1. Create ~/.blog_digest_env with your email credentials"
echo "2. Test the script: ~/run_blog_digest.sh"
echo "3. The script will run daily at 8 AM"
echo "4. Check logs at: ~/blog_digest.log"
echo ""
echo "To change the schedule, edit crontab with: crontab -e"
