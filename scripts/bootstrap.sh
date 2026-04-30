#!/bin/bash
# =============================================================================
# WORKSTATION BOOTSTRAP (Final Cluster Edition)
# =============================================================================
# 1. Installs System Tools, Tailscale, Standard Utils
# 2. Configures Security (Touch ID / SSH Key Sudo) - Auto-repairs if needed
# 3. Configures Services (Headless Tailscale)
# 4. Installs Nerd Fonts & Casks
# 5. Configures Shell (Zsh + Starship + Plugins)

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🚀 Starting Workstation Bootstrap...${NC}"

# =============================================================================
# 1. PACKAGE MANAGER & TOOLS
# =============================================================================
echo -e "${YELLOW}📦 Setting up System Tools...${NC}"

# Detect OS & Install Homebrew
OS_TYPE="unknown"
if [[ "$OSTYPE" == "darwin"* ]]; then
    OS_TYPE="macos"
    if ! command -v brew >/dev/null 2>&1; then
        echo -e "${YELLOW}Installing Homebrew...${NC}"
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        if [[ $(uname -m) == "arm64" ]]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        fi
    else
        echo -e "${GREEN}✅ Homebrew already installed${NC}"
    fi
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS_TYPE="linux"
    if command -v apt >/dev/null 2>&1; then
        sudo apt update
    fi
fi

# Function to install tools idempotently (Formula OR Cask)
install_tool() {
    local package="$1"

    if [[ "$OS_TYPE" == "macos" ]]; then
        # Check if installed as a Formula OR a Cask to avoid "Warning: Not upgrading..."
        if brew list --formula "$package" >/dev/null 2>&1 || brew list --cask "$package" >/dev/null 2>&1; then
            echo -e "${GREEN}✅ $package already installed${NC}"
            return
        fi
        echo -e "${YELLOW}Installing $package...${NC}"
        brew install "$package"

    elif [[ "$OS_TYPE" == "linux" ]]; then
        if dpkg -s "$package" >/dev/null 2>&1; then
            echo -e "${GREEN}✅ $package already installed${NC}"
            return
        fi
        echo -e "${YELLOW}Installing $package...${NC}"
        sudo apt install -y "$package"
    fi
}

# Standard Suite + Security Deps
TOOLS=("git" "curl" "wget" "vim" "tree" "htop" "jq" "fzf" "direnv" "rust" "cmake" "pyenv" "zsh" "gh" "tmux" "iperf3" "ncdu" "watch" "1password-cli" "tailscale")

for tool in "${TOOLS[@]}"; do
    install_tool "$tool"
done

# =============================================================================
# 2. SECURITY & TOUCH ID SETUP
# =============================================================================
echo -e "${YELLOW}🔐 Configuring Security & Touch ID Sudo...${NC}"

if [[ "$OS_TYPE" == "macos" ]]; then
    # A. Check/Install the PAM Module
    PAM_LIB="/opt/homebrew/lib/libpam_ssh_agent.so"

    if [ ! -f "$PAM_LIB" ]; then
        echo -e "${YELLOW}Compiling PAM SSH Agent module...${NC}"
        BUILD_DIR=$(mktemp -d)
        git clone https://github.com/nresare/pam-ssh-agent.git "$BUILD_DIR"

        pushd "$BUILD_DIR" > /dev/null
        cargo build --release
        sudo cp target/release/libpam_ssh_agent.dylib "$PAM_LIB"
        popd > /dev/null
        rm -rf "$BUILD_DIR"
        echo -e "${GREEN}✅ Module installed to $PAM_LIB${NC}"
    else
        echo -e "${GREEN}✅ PAM module already exists${NC}"
    fi

    # B. Configure /etc/pam.d/sudo (Only edits if missing)
    AUTH_LINE="auth       sufficient     $PAM_LIB file=~/.ssh/authorized_keys"
    PAM_FILE="/etc/pam.d/sudo"

    # We use sudo grep to check the file content without needing a password if already auth'd
    if ! sudo grep -q "libpam_ssh_agent.so" "$PAM_FILE"; then
        echo -e "${YELLOW}Updating $PAM_FILE (Password required to fix sudo)...${NC}"
        sudo cp "$PAM_FILE" "${PAM_FILE}.bak"
        echo "$AUTH_LINE" | cat - "${PAM_FILE}.bak" | sudo tee "$PAM_FILE" > /dev/null
        echo -e "${GREEN}✅ Sudo config repaired${NC}"
    else
        echo -e "${GREEN}✅ Sudo config is correct${NC}"
    fi

    # C. Configure /etc/sudoers (Persist SSH_AUTH_SOCK)
    SUDOERS_DROPIN="/private/etc/sudoers.d/keep_ssh_sock"
    if [ ! -f "$SUDOERS_DROPIN" ]; then
        echo -e "${YELLOW}Persisting SSH socket in sudoers...${NC}"
        echo 'Defaults env_keep += "SSH_AUTH_SOCK"' | sudo tee "$SUDOERS_DROPIN" > /dev/null
        sudo chmod 440 "$SUDOERS_DROPIN"
        echo -e "${GREEN}✅ Sudoers updated${NC}"
    else
        echo -e "${GREEN}✅ Sudoers persistence active${NC}"
    fi
fi

# =============================================================================
# 3. SERVICE CONFIGURATION
# =============================================================================
echo -e "${YELLOW}⚙️  Configuring Services...${NC}"

if [[ "$OS_TYPE" == "macos" ]]; then
    if ! sudo brew services list | grep -q "tailscale.*started"; then
        echo -e "${YELLOW}Starting Tailscale Headless Service...${NC}"
        # If Step 2 worked/existed, this sudo should be passwordless via SSH key
        sudo brew services start tailscale
    else
        echo -e "${GREEN}✅ Tailscale headless service is running${NC}"
    fi
elif [[ "$OS_TYPE" == "linux" ]]; then
    sudo systemctl enable --now tailscaled
fi

# =============================================================================
# 4. FONTS & CASKS (macOS Only)
# =============================================================================
if [[ "$OS_TYPE" == "macos" ]]; then
    echo -e "${YELLOW}🎨 Installing Fonts...${NC}"

    if ! brew tap | grep -q "homebrew/cask-fonts"; then
        brew tap homebrew/cask-fonts 2>/dev/null || true
    fi

    if ! brew list --cask font-hack-nerd-font >/dev/null 2>&1; then
        echo -e "${YELLOW}Installing Hack Nerd Font...${NC}"
        brew install --cask font-hack-nerd-font
    else
        echo -e "${GREEN}✅ Hack Nerd Font already installed${NC}"
    fi
fi

# =============================================================================
# 5. SHELL SETUP (ZSH + PLUGINS)
# =============================================================================
echo -e "${YELLOW}🐚 Setting up Shell Environment...${NC}"

# Install Oh My Zsh
if [ ! -d "$HOME/.oh-my-zsh" ]; then
    echo -e "${YELLOW}Installing Oh My Zsh...${NC}"
    sh -c "$(curl -fsSL https://raw.github.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended
else
    echo -e "${GREEN}✅ Oh My Zsh already installed${NC}"
fi

# --- Zsh Plugins ---
ZSH_CUSTOM="$HOME/.oh-my-zsh/custom"

# zsh-autosuggestions
if [ ! -d "$ZSH_CUSTOM/plugins/zsh-autosuggestions" ]; then
    echo -e "${YELLOW}Installing zsh-autosuggestions...${NC}"
    git clone https://github.com/zsh-users/zsh-autosuggestions ${ZSH_CUSTOM}/plugins/zsh-autosuggestions
else
    echo -e "${GREEN}✅ zsh-autosuggestions installed${NC}"
fi

# zsh-syntax-highlighting
if [ ! -d "$ZSH_CUSTOM/plugins/zsh-syntax-highlighting" ]; then
    echo -e "${YELLOW}Installing zsh-syntax-highlighting...${NC}"
    git clone https://github.com/zsh-users/zsh-syntax-highlighting.git ${ZSH_CUSTOM}/plugins/zsh-syntax-highlighting
else
    echo -e "${GREEN}✅ zsh-syntax-highlighting installed${NC}"
fi

# Install Starship
if ! command -v starship >/dev/null 2>&1; then
    echo -e "${YELLOW}Installing Starship...${NC}"
    curl -sS https://starship.rs/install.sh | sh -s -- --yes
else
    echo -e "${GREEN}✅ Starship already installed${NC}"
fi

# -----------------------------------------------------------------------------
# CONFIG: STARSHIP (Unicode Safe via Python)
# -----------------------------------------------------------------------------
mkdir -p "$HOME/.config"

cat > /tmp/gen_starship.py << 'EOF'
import os

L_RND = "\ue0b6"
R_ARR = "\ue0b0"
R_RND = "\ue0b4"
GIT_ICON = "\uf418"
CLOCK_ICON = "\uf43a"
MAC_ICON = "\U000f0035"

toml_content = f"""
"$schema" = 'https://starship.rs/config-schema.json'
palette = 'gruvbox_dark'

format = \"\"\"
[{L_RND}](color_orange)\\
$os\\
$custom\\
$hostname\\
[{R_ARR}](bg:color_yellow fg:color_orange)\\
$directory\\
[{R_ARR}](fg:color_yellow bg:color_aqua)\\
$git_branch\\
$git_status\\
[{R_ARR}](fg:color_aqua bg:color_blue)\\
$c\\
$cpp\\
$rust\\
$golang\\
$nodejs\\
$php\\
$java\\
$kotlin\\
$haskell\\
$python\\
[{R_ARR}](fg:color_blue bg:color_bg3)\\
$docker_context\\
$conda\\
$pixi\\
[{R_ARR}](fg:color_bg3 bg:color_bg1)\\
$time\\
[{R_RND} ](fg:color_bg1)\\
$line_break$character\"\"\"

[palettes.gruvbox_dark]
color_fg0 = '#fbf1c7'
color_bg1 = '#3c3836'
color_bg3 = '#665c54'
color_blue = '#458588'
color_aqua = '#689d6a'
color_green = '#98971a'
color_orange = '#d65d0e'
color_purple = '#b16286'
color_red = '#cc241d'
color_yellow = '#d79921'

[os]
disabled = false
style = "bg:color_orange fg:color_fg0"
format = "[$symbol]($style)"

[os.symbols]
Windows = "󰍲 "
Ubuntu = "󰕈 "
Macos = "{MAC_ICON} "
Linux = "󰌽 "

[username]
disabled = true

[custom.root_user]
command = "whoami"
when = ''' test "$(whoami)" = "root" '''
style = "bg:color_orange bold fg:color_red"
format = '[ $output ]($style)'

[hostname]
disabled = false
ssh_only = false
style = "bg:color_orange fg:color_fg0"
format = '[ $hostname ]($style)'

[directory]
style = "fg:color_fg0 bg:color_yellow"
format = "[ $path ]($style)"
truncation_length = 3
truncation_symbol = "…/"

[git_branch]
symbol = "{GIT_ICON}"
style = "bg:color_aqua"
format = '[[ $symbol $branch ](fg:color_fg0 bg:color_aqua)]($style)'

[git_status]
style = "bg:color_aqua"
format = '[[($all_status$ahead_behind )](fg:color_fg0 bg:color_aqua)]($style)'

[python]
symbol = ""
style = "bg:color_blue"
format = '[[ $symbol( $version) ](fg:color_fg0 bg:color_blue)]($style)'
detect_files = ["setup.py", "requirements.txt", "pyproject.toml", "Pipfile", "tox.ini", "poetry.lock"]
detect_extensions = []

[nodejs]
symbol = ""
style = "bg:color_blue"
format = '[[ $symbol( $version) ](fg:color_fg0 bg:color_blue)]($style)'

[rust]
symbol = ""
style = "bg:color_blue"
format = '[[ $symbol( $version) ](fg:color_fg0 bg:color_blue)]($style)'

[docker_context]
symbol = ""
style = "bg:color_bg3"
format = '[[ $symbol( $context) ](fg:#83a598 bg:color_bg3)]($style)'

[time]
disabled = false
time_format = "%R"
style = "bg:color_bg1"
format = '[[ {CLOCK_ICON} $time ](fg:color_fg0 bg:color_bg1)]($style)'

[character]
disabled = false
success_symbol = '[➜](bold fg:color_green)'
error_symbol = '[✗](bold fg:color_red)'
"""

file_path = os.path.expanduser("~/.config/starship.toml")
with open(file_path, "w", encoding="utf-8") as f:
    f.write(toml_content)

print(f"Successfully generated {file_path}")
EOF

python3 /tmp/gen_starship.py
rm /tmp/gen_starship.py

# -----------------------------------------------------------------------------
# CONFIG: ZSHRC
# -----------------------------------------------------------------------------
echo -e "${YELLOW}📝 Updating .zshrc...${NC}"

cat > "$HOME/.zshrc" << 'EOF'
# Fix for sudo/root permission warnings
ZSH_DISABLE_COMPFIX="true"

export ZSH="$HOME/.oh-my-zsh"
ZSH_THEME=""

# --- PLUGINS ---
plugins=(git zsh-autosuggestions zsh-syntax-highlighting)

# --- COMPLETIONS ---
if [ -d "$HOME/.docker/completions" ]; then
    fpath=("$HOME/.docker/completions" $fpath)
fi

source $ZSH/oh-my-zsh.sh

# --- USER CONFIG ---
eval "$(starship init zsh)"
eval "$(direnv hook zsh)"

# Pyenv
export PYENV_ROOT="$HOME/.pyenv"
[[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init - zsh)"

# Path Exports
if [[ "$OSTYPE" == "darwin"* ]]; then
    export PATH="/opt/homebrew/opt/openssh/bin:$PATH"
fi
export PATH="$HOME/.local/bin:$PATH"

# SSH Agent Forwarding Fix
if [ -z "$SSH_CONNECTION" ]; then
    export SSH_AUTH_SOCK="$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
fi
EOF

# -----------------------------------------------------------------------------
# CONFIG: ZPROFILE & ENV
# -----------------------------------------------------------------------------
mkdir -p "$HOME/.local/bin"

cat > "$HOME/.zprofile" << 'EOF'
if [[ "$OSTYPE" == "darwin"* ]]; then
    if [[ $(uname -m) == "arm64" ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ $(uname -m) == "x86_64" ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
fi
EOF

cat > "$HOME/.local/bin/env" << 'EOF'
#!/bin/sh
case ":${PATH}:" in
    *:"$HOME/.local/bin":*) ;;
    *) export PATH="$HOME/.local/bin:$PATH" ;;
esac
EOF
chmod +x "$HOME/.local/bin/env"

echo -e "${GREEN}🎉 Workstation Bootstrap Complete!${NC}"
echo "Run 'source ~/.zshrc' to apply changes."
