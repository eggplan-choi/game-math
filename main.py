import pygame
import sys
import os
import csv
import math
import random
import heapq
import array

# ==============================================================================
# 0. 사운드 믹서 사전 설정 및 엔진 초기화
# ==============================================================================
pygame.mixer.pre_init(44100, -16, 1, 512)
pygame.init()

SCREEN_WIDTH = 800
SCREEN_HEIGHT = 450
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("수학탐구학교: 2D 물리 게임 완전판 (렌더링 100% 반전)")
clock = pygame.time.Clock()

font_ui = pygame.font.SysFont(None, 24)
font_bold = pygame.font.SysFont(None, 28)
font_large = pygame.font.SysFont(None, 42)

TILE_SIZE = 40
MAP_COLS = 100
MAP_ROWS = 10
STAGE_CSV = "stage_100x10.csv"

def generate_beep(freq_start, freq_end, duration_ms, wave_type="square"):
    sample_rate = 44100
    n_samples = int(sample_rate * (duration_ms / 1000.0))
    buf = array.array('h')
    for i in range(n_samples):
        t = i / n_samples
        freq = freq_start + (freq_end - freq_start) * t
        phase = 2.0 * math.pi * freq * (i / sample_rate)
        if wave_type == "square":
            val = 14000 if math.sin(phase) >= 0 else -14000
        elif wave_type == "noise":
            val = random.randint(-14000, 14000)
        else:
            val = int(14000 * math.sin(phase))
        decay = 1.0 - t
        buf.append(int(val * decay))
    return pygame.mixer.Sound(buf)

snd_jump = generate_beep(200, 600, 100, "square")
snd_bounce = generate_beep(300, 900, 150, "square")
snd_item = generate_beep(500, 1000, 120, "triangle")
snd_switch = generate_beep(400, 300, 80, "square")
snd_death = generate_beep(400, 60, 250, "noise")
snd_troll = generate_beep(600, 150, 350, "sawtooth" if hasattr(math, "sin") else "square")
snd_reverse = generate_beep(250, 850, 400, "triangle")

# ==============================================================================
# 1. 시각 연출: 파티클 시스템
# ==============================================================================
class Particle:
    def __init__(self, x, y, color):
        self.x = float(x)
        self.y = float(y)
        self.color = color
        self.size = random.uniform(6.0, 11.0)
        angle = random.uniform(0, 2 * math.pi)
        speed = random.uniform(2.5, 7.5)
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed - 2.0
        self.gravity = 0.35
        self.life = 1.0
        self.decay = random.uniform(0.025, 0.045)

    def update(self):
        # 물리적으로 항상 +y 방향으로 중력 작용 (화면이 반전되면 시각적으로 위로 솟구침)
        self.vy += self.gravity
        self.x += self.vx
        self.y += self.vy
        self.life -= self.decay
        self.size = max(0.0, self.size - 0.15)

    def draw(self, surface, cam_x, ox, oy):
        if self.life > 0 and self.size > 0:
            rx = int(self.x - cam_x + ox)
            ry = int(self.y + oy)
            pygame.draw.rect(surface, self.color, (rx, ry, int(self.size), int(self.size)))

particles = []
screen_shake = 0.0

def trigger_explosion(x, y, color, count=25):
    global screen_shake
    screen_shake = 15.0
    for _ in range(count):
        particles.append(Particle(x, y, color))

# ==============================================================================
# 2. 동적 기믹 객체 모델링 클래스군
# ==============================================================================
class MovingPlatform:
    def __init__(self, x, y, width, height, move_range_x, move_speed):
        self.rect = pygame.Rect(x, y, width, height)
        self.start_x = float(x)
        self.end_x = float(x + move_range_x)
        self.speed_x = float(move_speed)
        self.x = float(x)

    def update(self):
        self.x += self.speed_x
        if self.x >= self.end_x or self.x <= self.start_x:
            self.speed_x *= -1.0
            self.x += self.speed_x
            return self.speed_x
        self.rect.x = int(self.x)
        return self.speed_x

class MovingHazard:
    def __init__(self, x, y, amplitude=70.0, omega=0.04):
        self.center_x = float(x)
        self.y = float(y)
        self.amplitude = float(amplitude)
        self.omega = float(omega)
        self.t = 0.0
        self.rect = pygame.Rect(x, y, TILE_SIZE, TILE_SIZE)

    def update(self):
        self.t += self.omega
        cur_x = self.center_x + self.amplitude * math.sin(self.t)
        self.rect.x = int(cur_x)

    def draw(self, surface, cam_x, ox, oy):
        r = pygame.Rect(self.rect.x - cam_x + ox, self.rect.y + oy, TILE_SIZE, TILE_SIZE)
        pygame.draw.rect(surface, (231, 76, 60), r)
        pygame.draw.rect(surface, (255, 255, 255), r, 2)

class CrumblingPlatform:
    def __init__(self, x, y):
        self.rect = pygame.Rect(x, y, TILE_SIZE, TILE_SIZE)
        self.stepped = False
        self.timer = 40
        self.respawn_timer = 0
        self.is_active = True

    def reset(self):
        self.stepped = False
        self.timer = 40
        self.respawn_timer = 0
        self.is_active = True

    def update(self):
        if self.stepped and self.is_active:
            self.timer -= 1
            if self.timer <= 0:
                self.is_active = False
                self.respawn_timer = 150

        if not self.is_active:
            self.respawn_timer -= 1
            if self.respawn_timer <= 0:
                self.reset()

    def draw(self, surface, cam_x, ox, oy):
        if self.is_active:
            r = pygame.Rect(self.rect.x - cam_x + ox, self.rect.y + oy, TILE_SIZE, TILE_SIZE)
            color = (180, 90, 40) if self.stepped and (self.timer // 4) % 2 == 0 else (210, 115, 45)
            pygame.draw.rect(surface, color, r)

class ToggleSwitchSystem:
    def __init__(self):
        self.is_on = False

    def toggle(self):
        self.is_on = not self.is_on
        snd_switch.play()

class HiddenBlock:
    def __init__(self, x, y):
        self.rect = pygame.Rect(x, y, TILE_SIZE, TILE_SIZE)
        self.is_revealed = False

    def draw(self, surface, cam_x, ox, oy):
        if self.is_revealed:
            r = pygame.Rect(self.rect.x - cam_x + ox, self.rect.y + oy, TILE_SIZE, TILE_SIZE)
            pygame.draw.rect(surface, (140, 160, 175), r)
            pygame.draw.rect(surface, (255, 255, 255), r, 2)

class FleeingPlatform:
    def __init__(self, x, y, max_retreat=75.0):
        self.origin_x = float(x)
        self.x = float(x)
        self.y = float(y)
        self.max_retreat = float(max_retreat)
        self.rect = pygame.Rect(x, y, TILE_SIZE * 2, TILE_SIZE)
        self.is_stepped = False

    def reset(self):
        self.x = self.origin_x
        self.rect.x = int(self.x)
        self.is_stepped = False

    def update(self, px, py, is_standing):
        self.is_stepped = is_standing
        if self.is_stepped:
            return

        dx = self.rect.centerx - px
        dy = self.rect.centery - py
        dist = math.hypot(dx, dy)

        if dist < 110.0 and dist > 0.001:
            direction = 1.0 if dx > 0 else -1.0
            self.x += direction * 2.4
            self.x = max(self.origin_x - self.max_retreat, min(self.origin_x + self.max_retreat, self.x))
        else:
            self.x += (self.origin_x - self.x) * 0.04
        self.rect.x = int(self.x)

    def draw(self, surface, cam_x, ox, oy):
        r = pygame.Rect(self.rect.x - cam_x + ox, self.rect.y + oy, self.rect.width, self.rect.height)
        color = (165, 105, 189) if self.is_stepped else (155, 89, 182)
        border_color = (46, 204, 113) if self.is_stepped else (255, 255, 255)
        pygame.draw.rect(surface, color, r)
        pygame.draw.rect(surface, border_color, r, 2)


# ==============================================================================
# 3. CSV 맵 생성 및 로드
# ==============================================================================
def create_default_100x10_csv():
    grid = [["0" for _ in range(MAP_COLS)] for _ in range(MAP_ROWS)]

    for c in range(MAP_COLS):
        grid[8][c] = "1"
        grid[9][c] = "1"

    grid[7][2] = "P"
    grid[6][9] = "1"
    grid[5][9] = "S"
    grid[7][14] = "2"

    for c in range(17, 23):
        grid[8][c] = "0"
        grid[9][c] = "0"
    grid[7][18] = "C"
    grid[7][20] = "C"
    grid[7][24] = "J"
    grid[6][26] = "1"
    grid[7][26] = "1"

    grid[7][30] = "M"
    grid[4][33] = "H"
    grid[3][35] = "1"

    for c in range(40, 45):
        grid[8][c] = "0"
        grid[9][c] = "2"
    grid[7][38] = "T"
    grid[6][41] = "B"
    grid[6][42] = "B"
    grid[6][43] = "B"

    grid[6][48] = "1"
    grid[5][48] = "F"

    for c in range(55, 62):
        grid[8][c] = "0"
        grid[9][c] = "0"
    grid[7][57] = "E"

    grid[7][65] = "W"
    
    # 뚫린 장벽 구조 구성 (역주행 시에도 동일하게 작동)
    for r in range(1, 4):
        grid[r][70] = "1"
    for r in range(6, 8):
        grid[r][70] = "1"
        
    grid[5][69] = "2"
    grid[5][71] = "2"

    for c in range(78, 86):
        grid[8][c] = "0"
        grid[9][c] = "0"

    grid[7][92] = "2"
    grid[6][95] = "1"
    grid[5][95] = "G"

    with open(STAGE_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        for row in grid:
            writer.writerow(row)

if not os.path.exists(STAGE_CSV):
    create_default_100x10_csv()
else:
    with open(STAGE_CSV, "r", encoding="utf-8-sig") as f:
        content = f.read()
        lines = content.split("\n")
        if len(lines) > 1 and len(lines[1].split(",")) > 70:
            if lines[1].split(",")[70] != "1":
                create_default_100x10_csv()

platforms = []
hazards = []
springs = []
shield_items = []
warp_items = []
moving_hazards = []
crumbling_platforms = []
toggle_blocks = []
hidden_blocks = []
fleeing_platforms = []
moving_platforms = []
switch_rect = None
real_goal = None
fake_goal = None
spawn_point = (80.0, 200.0)

toggle_system = ToggleSwitchSystem()
collision_grid = [[False for _ in range(MAP_COLS)] for _ in range(MAP_ROWS)]

def load_stage_data():
    global platforms, hazards, springs, shield_items, warp_items
    global moving_hazards, crumbling_platforms, toggle_blocks, hidden_blocks
    global fleeing_platforms, moving_platforms, switch_rect, real_goal, fake_goal, spawn_point
    global collision_grid

    platforms.clear()
    hazards.clear()
    springs.clear()
    shield_items.clear()
    warp_items.clear()
    moving_hazards.clear()
    crumbling_platforms.clear()
    toggle_blocks.clear()
    hidden_blocks.clear()
    fleeing_platforms.clear()
    moving_platforms.clear()
    switch_rect = None
    real_goal = None
    fake_goal = None
    toggle_system.is_on = False

    collision_grid = [[False for _ in range(MAP_COLS)] for _ in range(MAP_ROWS)]

    with open(STAGE_CSV, "r", encoding="utf-8-sig") as f:
        reader = list(csv.reader(f))
        for r, row in enumerate(reader):
            for c, val in enumerate(row):
                val = val.strip().upper()
                x = c * TILE_SIZE
                y = r * TILE_SIZE

                if val == "1":
                    platforms.append(pygame.Rect(x, y, TILE_SIZE, TILE_SIZE))
                    collision_grid[r][c] = True
                elif val == "2":
                    hazards.append(pygame.Rect(x, y, TILE_SIZE, TILE_SIZE))
                    collision_grid[r][c] = True
                elif val == "J":
                    springs.append(pygame.Rect(x + 5, y + 25, 30, 15))
                elif val == "S":
                    shield_items.append(pygame.Rect(x + 10, y + 10, 20, 20))
                elif val == "W":
                    warp_items.append(pygame.Rect(x + 10, y + 10, 20, 20))
                elif val == "M":
                    moving_hazards.append(MovingHazard(x, y, amplitude=70.0, omega=0.04))
                elif val == "C":
                    crumbling_platforms.append(CrumblingPlatform(x, y))
                elif val == "T":
                    switch_rect = pygame.Rect(x + 8, y + 24, 24, 16)
                elif val == "B":
                    toggle_blocks.append(pygame.Rect(x, y, TILE_SIZE, TILE_SIZE))
                elif val == "H":
                    hidden_blocks.append(HiddenBlock(x, y))
                elif val == "E":
                    fleeing_platforms.append(FleeingPlatform(x, y, max_retreat=75.0))
                elif val == "F":
                    fake_goal = pygame.Rect(x, y, TILE_SIZE, TILE_SIZE * 2)
                elif val == "G":
                    real_goal = pygame.Rect(x, y, TILE_SIZE, TILE_SIZE * 2)
                elif val == "P":
                    spawn_point = (float(x), float(y))

    moving_platforms.append(MovingPlatform(79 * TILE_SIZE, 6 * TILE_SIZE, 80, 20, move_range_x=220, move_speed=2.5))


# ==============================================================================
# 4. A* 최단 경로 탐색 알고리즘
# ==============================================================================
def find_a_star_path(start_pos, target_pos):
    sc = int(start_pos[0] // TILE_SIZE)
    sr = int(start_pos[1] // TILE_SIZE)
    tc = int(target_pos[0] // TILE_SIZE)
    tr = int(target_pos[1] // TILE_SIZE)

    if not (0 <= tr < MAP_ROWS and 0 <= tc < MAP_COLS): return []
    if collision_grid[tr][tc]: return []

    open_set = []
    heapq.heappush(open_set, (0, 0, (sr, sc)))
    came_from = {}
    g_score = {(sr, sc): 0}

    while open_set:
        _, cur_g, current = heapq.heappop(open_set)

        if current == (tr, tc):
            path = []
            curr = current
            while curr in came_from:
                path.append((curr[1] * TILE_SIZE + 4, curr[0] * TILE_SIZE + 4))
                curr = came_from[curr]
            path.reverse()
            return path

        cr, cc = current
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = cr + dr, cc + dc
            if 0 <= nr < MAP_ROWS and 0 <= nc < MAP_COLS:
                if collision_grid[nr][nc]: continue
                tentative_g = cur_g + 1
                if (nr, nc) not in g_score or tentative_g < g_score[(nr, nc)]:
                    g_score[(nr, nc)] = tentative_g
                    f = tentative_g + abs(nr - tr) + abs(nc - tc)
                    heapq.heappush(open_set, (f, tentative_g, (nr, nc)))
                    came_from[(nr, nc)] = current
    return []


# ==============================================================================
# 5. 플레이어 물리 및 상태 관리
# ==============================================================================
player_x = 0.0
player_y = 0.0
velocity_x = 0.0
velocity_y = 0.0

gravity = 0.78
jump_power = -14.6
speed = 5.6
spring_power = -21.5

is_grounded = False
has_shield = False
has_warp_ability = False
is_flying = False
fly_path = []
fly_speed = 11.0

coyote_timer = 0
COYOTE_MAX = 6
invincible_timer = 0
knockback_timer = 0
troll_timer = 0
reverse_announcement_timer = 0

is_reversed = False
is_game_cleared = False
death_count = 0

player_rect = pygame.Rect(0, 0, TILE_SIZE, TILE_SIZE)

def get_padded_rect(rect, pad):
    return pygame.Rect(rect.x + pad, rect.y + pad, rect.width - 2 * pad, rect.height - 2 * pad)

def reset_stage(full_restart=True):
    global player_x, player_y, velocity_x, velocity_y, is_grounded
    global has_shield, has_warp_ability, is_flying, fly_path
    global coyote_timer, invincible_timer, knockback_timer, troll_timer
    global is_reversed, is_game_cleared, screen_shake, reverse_announcement_timer

    was_reversed = is_reversed and not full_restart

    load_stage_data()
    
    if not was_reversed:
        is_reversed = False
        player_x = spawn_point[0]
        player_y = spawn_point[1]
    else:
        is_reversed = True
        player_x = float(real_goal.x)
        player_y = float(real_goal.y)
        reverse_announcement_timer = 90
        # 역주행 시 움직이는 발판 구간(78~85열)을 건너뛴 직후인 74열 바닥(7행)에 워프 스폰
        warp_items.append(pygame.Rect(74 * TILE_SIZE + 10, 7 * TILE_SIZE + 10, 20, 20))

    velocity_x = 0.0
    velocity_y = 0.0
    is_grounded = False
    has_shield = False
    has_warp_ability = False
    is_flying = False
    fly_path.clear()
    coyote_timer = 0
    invincible_timer = 0
    knockback_timer = 0
    troll_timer = 0
    is_game_cleared = False
    screen_shake = 0.0

reset_stage(full_restart=True)
world_surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))

# ==============================================================================
# 6. 메인 게임 루프
# ==============================================================================
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_r:
                reset_stage(full_restart=True)

            if not has_warp_ability and not is_flying and not is_game_cleared:
                if event.key == pygame.K_SPACE and coyote_timer > 0 and knockback_timer <= 0:
                    velocity_y = jump_power
                    coyote_timer = 0
                    is_grounded = False
                    snd_jump.play()

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if has_warp_ability and not is_flying:
                map_w = MAP_COLS * TILE_SIZE
                cam_x = max(0, min(map_w - SCREEN_WIDTH, player_rect.centerx - SCREEN_WIDTH // 2))
                mouse_world_x = float(event.pos[0] + cam_x)
                
                # 렌더링 역전 시, 마우스 Y좌표를 물리적 월드 Y좌표로 매핑
                if is_reversed:
                    mouse_world_y = float(SCREEN_HEIGHT - event.pos[1])
                else:
                    mouse_world_y = float(event.pos[1])

                path = find_a_star_path((player_x, player_y), (mouse_world_x, mouse_world_y))
                if path:
                    fly_path = path
                    is_flying = True
                    has_warp_ability = False
                    snd_bounce.play()

    if not is_game_cleared:
        for mh in moving_hazards:
            mh.update()
        for cp in crumbling_platforms:
            cp.update()

        feet_rect = pygame.Rect(player_rect.x, player_rect.y, player_rect.width, player_rect.height + 2)

        for fp in fleeing_platforms:
            is_standing = False
            horiz_overlap = (player_rect.right > fp.rect.left + 2) and (player_rect.left < fp.rect.right - 2)
            if horiz_overlap and velocity_y >= 0 and abs((player_y + TILE_SIZE) - fp.rect.top) < 1.0:
                is_standing = True
            fp.update(player_rect.centerx, player_rect.centery, is_standing)

        plat_carrier_dx = 0.0
        for mp in moving_platforms:
            dx = mp.update()
            if feet_rect.colliderect(mp.rect) and velocity_y >= 0:
                plat_carrier_dx = dx

    if not is_game_cleared:
        if is_flying:
            if fly_path:
                target_node = fly_path[0]
                tdx = target_node[0] - player_x
                tdy = target_node[1] - player_y
                dist = math.hypot(tdx, tdy)

                if dist < fly_speed:
                    player_x = float(target_node[0])
                    player_y = float(target_node[1])
                    fly_path.pop(0)
                else:
                    player_x += (tdx / dist) * fly_speed
                    player_y += (tdy / dist) * fly_speed
                player_rect.x = int(player_x)
                player_rect.y = int(player_y)
            else:
                is_flying = False
                velocity_x = 0.0
                velocity_y = 0.0

        elif has_warp_ability:
            velocity_x = 0.0
            velocity_y = 0.0
            player_rect.x = int(player_x)
            player_rect.y = int(player_y)

        else:
            if knockback_timer > 0:
                knockback_timer -= 1
                velocity_x *= 0.88
            else:
                keys = pygame.key.get_pressed()
                velocity_x = 0.0
                if keys[pygame.K_LEFT]:  velocity_x = -speed
                if keys[pygame.K_RIGHT]: velocity_x = speed

            player_x += velocity_x + plat_carrier_dx
            player_rect.x = int(player_x)

            solids = list(platforms)
            if toggle_system.is_on:
                solids.extend(toggle_blocks)
            solids.extend([cp.rect for cp in crumbling_platforms if cp.is_active])
            solids.extend([hb.rect for hb in hidden_blocks if hb.is_revealed])
            solids.extend([fp.rect for fp in fleeing_platforms])
            solids.extend([mp.rect for mp in moving_platforms])

            for block in solids:
                if player_rect.colliderect(block):
                    if (velocity_x + plat_carrier_dx) > 0:
                        player_rect.right = block.left
                    elif (velocity_x + plat_carrier_dx) < 0:
                        player_rect.left = block.right
                    player_x = float(player_rect.x)

            # 물리 엔진 상에서는 항상 양(+)의 정상 중력 유지
            velocity_y += gravity
            player_y += velocity_y
            player_rect.y = int(player_y)
            is_grounded = False

            for hb in hidden_blocks:
                if not hb.is_revealed and velocity_y < 0 and player_rect.colliderect(hb.rect):
                    hb.is_revealed = True
                    player_rect.top = hb.rect.bottom
                    player_y = float(player_rect.y)
                    velocity_y = 0.0
                    snd_bounce.play()

            for block in solids:
                if player_rect.colliderect(block):
                    if velocity_y > 0:
                        player_rect.bottom = block.top
                        player_y = float(player_rect.y)
                        velocity_y = 0.0
                        is_grounded = True
                        for cp in crumbling_platforms:
                            if block == cp.rect and cp.is_active: cp.stepped = True
                    elif velocity_y < 0:
                        player_rect.top = block.bottom
                        player_y = float(player_rect.y)
                        velocity_y = 0.0

            for spring in springs:
                if player_rect.colliderect(spring) and velocity_y > 0:
                    player_rect.bottom = spring.top
                    player_y = float(player_rect.y)
                    velocity_y = spring_power
                    is_grounded = False
                    snd_bounce.play()

            if switch_rect and player_rect.colliderect(switch_rect):
                if velocity_y > 0 and player_rect.bottom - velocity_y <= switch_rect.top + 12:
                    toggle_system.toggle()
                    player_rect.bottom = switch_rect.top
                    player_y = float(player_rect.y)
                    velocity_y = -6.0

            if is_grounded:
                coyote_timer = COYOTE_MAX
            else:
                coyote_timer = max(0, coyote_timer - 1)

            for shield in shield_items[:]:
                if player_rect.colliderect(shield):
                    has_shield = True
                    shield_items.remove(shield)
                    snd_item.play()

            for warp in warp_items[:]:
                if player_rect.colliderect(warp):
                    has_warp_ability = True
                    warp_items.remove(warp)
                    velocity_x = 0.0
                    velocity_y = 0.0
                    snd_item.play()

            if fake_goal and player_rect.colliderect(fake_goal):
                troll_timer = 120
                knockback_timer = 20
                velocity_x = -15.0
                velocity_y = -10.0
                snd_troll.play()

            if not is_reversed:
                if real_goal and player_rect.colliderect(real_goal):
                    is_reversed = True
                    reverse_announcement_timer = 150
                    velocity_x = 0.0
                    velocity_y = 0.0
                    snd_reverse.play()
                    trigger_explosion(player_rect.centerx, player_rect.centery, (155, 89, 182), 40)
                    
                    # 역주행 워프 아이템 스폰 (물리적 바닥 74열 7행)
                    warp_items.append(pygame.Rect(74 * TILE_SIZE + 10, 7 * TILE_SIZE + 10, 20, 20))
            else:
                return_rect = pygame.Rect(int(spawn_point[0]), int(spawn_point[1]), TILE_SIZE, TILE_SIZE * 2)
                if player_rect.colliderect(return_rect):
                    is_game_cleared = True
                    snd_item.play()

        if invincible_timer > 0:
            invincible_timer -= 1

        all_hazards = list(hazards) + [mh.rect for mh in moving_hazards]
        player_hitbox = get_padded_rect(player_rect, 4)

        for hz in all_hazards:
            if player_hitbox.colliderect(get_padded_rect(hz, 5)):
                if has_shield:
                    has_shield = False
                    invincible_timer = 35
                    knockback_timer = 16

                    if player_rect.centerx < hz.centerx:
                        velocity_x = -13.0
                    else:
                        velocity_x = 13.0
                    velocity_y = -7.5

                    snd_bounce.play()
                    trigger_explosion(player_rect.centerx, player_rect.centery, (0, 240, 255), 15)
                elif invincible_timer <= 0:
                    death_count += 1
                    snd_death.play()
                    trigger_explosion(player_rect.centerx, player_rect.centery, (241, 196, 15), 30)
                    reset_stage(full_restart=False)
                    break

        if player_y > MAP_ROWS * TILE_SIZE + 50:
            death_count += 1
            snd_death.play()
            reset_stage(full_restart=False)

    for p in particles[:]:
        p.update()
        if p.life <= 0 or p.size <= 0:
            particles.remove(p)

    map_pixel_width = MAP_COLS * TILE_SIZE
    camera_x = max(0, min(map_pixel_width - SCREEN_WIDTH, player_rect.centerx - SCREEN_WIDTH // 2))

    ox = oy = 0
    if screen_shake > 0:
        ox = random.uniform(-screen_shake, screen_shake)
        oy = random.uniform(-screen_shake, screen_shake)
        screen_shake = max(0.0, screen_shake * 0.9 - 0.2)

    world_surface.fill((16, 20, 28))

    for b in platforms:
        rx = b.x - camera_x + ox
        if -TILE_SIZE <= rx <= SCREEN_WIDTH:
            pygame.draw.rect(world_surface, (41, 128, 185), (rx, b.y + oy, b.width, b.height))

    for tb in toggle_blocks:
        rx = tb.x - camera_x + ox
        if -TILE_SIZE <= rx <= SCREEN_WIDTH:
            if toggle_system.is_on:
                pygame.draw.rect(world_surface, (52, 152, 219), (rx, tb.y + oy, tb.width, tb.height))
                pygame.draw.rect(world_surface, (255, 255, 255), (rx, tb.y + oy, tb.width, tb.height), 2)
            else:
                pygame.draw.rect(world_surface, (50, 60, 80), (rx, tb.y + oy, tb.width, tb.height), 1)

    if switch_rect:
        rx = switch_rect.x - camera_x + ox
        c_color = (46, 204, 113) if toggle_system.is_on else (142, 68, 173)
        pygame.draw.rect(world_surface, c_color, (rx, switch_rect.y + oy, switch_rect.width, switch_rect.height))
        pygame.draw.rect(world_surface, (255, 255, 255), (rx, switch_rect.y + oy, switch_rect.width, switch_rect.height), 2)

    for sp in springs:
        rx = sp.x - camera_x + ox
        pygame.draw.rect(world_surface, (155, 89, 182), (rx, sp.y + oy, sp.width, sp.height))

    for mh in moving_hazards:
        mh.draw(world_surface, camera_x, ox, oy)
    for cp in crumbling_platforms:
        cp.draw(world_surface, camera_x, ox, oy)
    for hb in hidden_blocks:
        hb.draw(world_surface, camera_x, ox, oy)
    for fp in fleeing_platforms:
        fp.draw(world_surface, camera_x, ox, oy)
    for mp in moving_platforms:
        rx = mp.rect.x - camera_x + ox
        pygame.draw.rect(world_surface, (26, 188, 156), (rx, mp.rect.y + oy, mp.rect.width, mp.rect.height))

    for hz in hazards:
        rx = hz.x - camera_x + ox
        if -TILE_SIZE <= rx <= SCREEN_WIDTH:
            pygame.draw.rect(world_surface, (231, 76, 60), (rx, hz.y + oy, hz.width, hz.height))

    for s_item in shield_items:
        rx = s_item.x - camera_x + ox
        pygame.draw.rect(world_surface, (0, 240, 255), (rx, s_item.y + oy, s_item.width, s_item.height))
    for w_item in warp_items:
        rx = w_item.x - camera_x + ox
        pygame.draw.rect(world_surface, (230, 126, 34), (rx, w_item.y + oy, w_item.width, w_item.height))

    if fake_goal:
        rx = fake_goal.x - camera_x + ox
        pygame.draw.rect(world_surface, (46, 204, 113), (rx, fake_goal.y + oy, fake_goal.width, fake_goal.height))
        pygame.draw.rect(world_surface, (241, 196, 15), (rx, fake_goal.y + oy, fake_goal.width, fake_goal.height), 2)

    if not is_reversed:
        if real_goal:
            rx = real_goal.x - camera_x + ox
            pygame.draw.rect(world_surface, (46, 204, 113), (rx, real_goal.y + oy, real_goal.width, real_goal.height))
    else:
        rx = spawn_point[0] - camera_x + ox
        pygame.draw.rect(world_surface, (155, 89, 182), (rx, spawn_point[1] + oy, TILE_SIZE, TILE_SIZE * 2))
        pygame.draw.rect(world_surface, (255, 255, 255), (rx, spawn_point[1] + oy, TILE_SIZE, TILE_SIZE * 2), 2)

    if is_flying and len(fly_path) > 1:
        pts = [(p[0] - camera_x + ox + 16, p[1] + oy + 16) for p in fly_path]
        pygame.draw.lines(world_surface, (255, 255, 0), False, pts, 2)

    for p in particles:
        p.draw(world_surface, camera_x, ox, oy)

    rx = player_rect.x - camera_x + ox
    ry = player_rect.y + oy
    pygame.draw.rect(world_surface, (241, 196, 15), (rx, ry, TILE_SIZE, TILE_SIZE))
    if has_shield:
        pygame.draw.rect(world_surface, (0, 240, 255), (rx, ry, TILE_SIZE, TILE_SIZE), 4)
    elif has_warp_ability:
        pygame.draw.rect(world_surface, (230, 126, 34), (rx, ry, TILE_SIZE, TILE_SIZE), 3)

    if is_reversed:
        flipped_world = pygame.transform.flip(world_surface, False, True)
        screen.blit(flipped_world, (0, 0))
    else:
        screen.blit(world_surface, (0, 0))

    # --------------------------------------------------------------------------
    # (7) 상단 HUD 및 텍스트 오버레이
    # --------------------------------------------------------------------------
    if has_warp_ability:
        prompt = font_bold.render("이동시키고자 하는 위치를 마우스로 클릭하세요!", True, (255, 240, 0))
        p_bg = pygame.Rect(SCREEN_WIDTH // 2 - prompt.get_width() // 2 - 14, 60, prompt.get_width() + 28, prompt.get_height() + 12)
        pygame.draw.rect(screen, (10, 14, 24), p_bg)
        pygame.draw.rect(screen, (230, 126, 34), p_bg, 2)
        screen.blit(prompt, (SCREEN_WIDTH // 2 - prompt.get_width() // 2, 66))

    if troll_timer > 0:
        troll_timer -= 1
        t_msg = font_large.render("FAKE GOAL! YOU GOT TROLLED!", True, (255, 60, 60))
        screen.blit(t_msg, (SCREEN_WIDTH // 2 - t_msg.get_width() // 2, 110))

    if reverse_announcement_timer > 0:
        reverse_announcement_timer -= 1
        r_msg = font_large.render("GRAVITY INVERTED! ESCAPE BACK TO START!", True, (190, 100, 255))
        screen.blit(r_msg, (SCREEN_WIDTH // 2 - r_msg.get_width() // 2, 110))

    if is_game_cleared:
        c_msg = font_large.render("ALL MISSIONS CLEARED! YOU ESCAPED!", True, (46, 204, 113))
        screen.blit(c_msg, (SCREEN_WIDTH // 2 - c_msg.get_width() // 2, SCREEN_HEIGHT // 2 - 20))

    mode_str = "MODE: REVERSED (RETURN!)" if is_reversed else "MODE: FORWARD (TO GOAL)"
    hud_progress = f"Pos: {int(player_x // TILE_SIZE)}m | {mode_str} | Deaths: {death_count}"
    hud_items = f"Shield: {'ON' if has_shield else 'OFF'} | Switch: {'ON' if toggle_system.is_on else 'OFF'}"
    t_hud1 = font_ui.render(hud_progress, True, (220, 220, 220))
    t_hud2 = font_ui.render(hud_items, True, (180, 200, 220))
    screen.blit(t_hud1, (20, 15))
    screen.blit(t_hud2, (SCREEN_WIDTH - t_hud2.get_width() - 20, 15))

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
sys.exit()