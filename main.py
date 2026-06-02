import discord
from discord.ext import commands
from discord import app_commands
import random
import os
from collections import deque
from dotenv import load_dotenv

current_uno_game = None

intents = discord.Intents.default()
intents.message_content = True
intents.members = True 

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

class UnoCard:
    def __init__(self, color, value):
        self.color = color
        self.value = value

    def __str__(self):
        if self.color == "wild":
            return f"{self.value.capitalize()}"
        return f"{self.color.capitalize()} {self.value}"

    def is_wild(self):
        return self.color == "wild"

    def __eq__(self, other):
        if not isinstance(other, UnoCard):
            return NotImplemented
        return self.color == other.color and self.value == other.value

    def __hash__(self):
        return hash((self.color, self.value))

class UnoDeck:
    def __init__(self):
        self.cards = deque()
        self._create_deck()
        self.discard_pile = []
        self.deal_initial_card()

    def _create_deck(self):
        colors = ["red", "green", "blue", "yellow"]
        values = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "Skip", "Reverse", "Draw Two"]
        wild_cards = ["Wild", "Wild Draw Four"]

        deck_list = []
        for color in colors:
            deck_list.append(UnoCard(color, "0"))
            for _ in range(2):
                for value in values[1:]:
                    deck_list.append(UnoCard(color, value))

        for _ in range(4):
            for value in wild_cards:
                deck_list.append(UnoCard("wild", value))

        random.shuffle(deck_list)
        self.cards = deque(deck_list)

    def deal_initial_card(self):
        initial_card = self.draw_card(1)[0]
        while initial_card.is_wild() or initial_card.value in ["Skip", "Reverse", "Draw Two"]:
            self.cards.append(initial_card)
            initial_card = self.draw_card(1)[0]
        self.discard_pile.append(initial_card)

    def reshuffle_discard_pile(self):
        last_card = self.discard_pile.pop()
        random.shuffle(self.discard_pile)
        self.cards.extend(self.discard_pile)
        self.discard_pile = [last_card]

    def draw_card(self, num=1):
        drawn_cards = []
        for _ in range(num):
            if not self.cards:
                self.reshuffle_discard_pile()
            drawn_cards.append(self.cards.popleft())
        return drawn_cards

    def place_on_discard_pile(self, card):
        self.discard_pile.append(card)

    def get_top_card(self):
        return self.discard_pile[-1] if self.discard_pile else None


class UnoPlayer:
    def __init__(self, discord_user_id, discord_user_name):
        self.discord_user_id = discord_user_id
        self.discord_user_name = discord_user_name
        self.hand = []
        self.said_uno = False

    def add_card(self, card):
        self.hand.append(card)
        self.hand.sort(key=lambda card: (card.color, card.value))

    def remove_card(self, card):
        try:
            self.hand.remove(card)
            return True
        except ValueError:
            return False

    def get_hand_display(self):
        if not self.hand:
            return "Không có bài trên tay."
        return "\n".join([f"**{i+1}.** {str(card)}" for i, card in enumerate(self.hand)])

class UnoGame:
    def __init__(self, host_id, host_name, channel_id):
        self.host = UnoPlayer(host_id, host_name)
        self.channel_id = channel_id
        self.players = [self.host]
        self.deck = UnoDeck()
        self.current_player_index = 0
        self.direction = 1
        self.game_started = False
        self.pending_draw_cards = 0
        self.current_color_choice = None
        self.is_paused = False


    def add_player(self, player_id, player_name):
        if not self.game_started and len(self.players) < 10:
            player_ids_in_game = [p.discord_user_id for p in self.players]
            if player_id not in player_ids_in_game:
                player = UnoPlayer(player_id, player_name)
                self.players.append(player)
                return True
        return False

    def remove_player(self, player_id):
        player_to_remove_index = -1
        for i, p in enumerate(self.players):
            if p.discord_user_id == player_id:
                player_to_remove_index = i
                break

        if player_to_remove_index != -1:
            removed_player = self.players.pop(player_to_remove_index)
            if removed_player.discord_user_id == self.host.discord_user_id:
                return "host_forfeited"

            if len(self.players) > 0:
                self.current_player_index %= len(self.players)
                if player_to_remove_index == self.current_player_index and len(self.players) > 0:
                    self.current_player_index = (self.current_player_index + self.direction) % len(self.players)
                elif player_to_remove_index < self.current_player_index:
                    self.current_player_index = (self.current_player_index - 1) % len(self.players)
            else:
                return "no_players_left"
            return "success"
        return "not_found"

    def start_game(self):
        if len(self.players) < 2:
            return False, "Cần ít nhất 2 người để chơi!"

        self.deck = UnoDeck()
        for player in self.players:
            player.hand = self.deck.draw_card(7)
            player.said_uno = False

        self.current_player_index = random.randint(0, len(self.players) - 1)
        self.game_started = True
        self.current_color_choice = self.deck.get_top_card().color if self.deck.get_top_card().color != "wild" else None
        self.is_paused = False
        return True, ""

    def get_current_player(self):
        if not self.players or not (0 <= self.current_player_index < len(self.players)):
            return None
        return self.players[self.current_player_index]

    def get_top_card(self):
        return self.deck.discard_pile[-1] if self.deck.discard_pile else None

    def is_valid_play(self, card_to_play):
        top_card = self.get_top_card()
        if not top_card:
            return True

        if self.pending_draw_cards > 0:
            if (card_to_play.value == "Draw Two" and top_card.value == "Draw Two") or \
               (card_to_play.value == "Wild Draw Four" and top_card.value == "Wild Draw Four"):
                return True
            return False

        if card_to_play.is_wild():
            return True

        if self.current_color_choice:
            return card_to_play.color == self.current_color_choice or card_to_play.value == top_card.value
        
        return card_to_play.color == top_card.color or card_to_play.value == top_card.value

    async def play_card(self, interaction: discord.Interaction, player_id: int, card_index: int, chosen_color: str = None):
        global current_uno_game

        if self.is_paused:
            return "Game đang tạm dừng. Vui lòng đợi host tiếp tục game."

        player = next((p for p in self.players if p.discord_user_id == player_id), None)
        if not player:
            return "Bạn không phải là người chơi trong ván này."

        current_player = self.get_current_player()
        if not current_player or current_player.discord_user_id != player_id:
            return "Chưa đến lượt của bạn!"

        if not (0 <= card_index - 1 < len(player.hand)):
            return f"Số thứ tự bài {card_index} không hợp lệ. Vui lòng kiểm tra lại bằng `/hand`."

        card_to_play = player.hand[card_index - 1]
        top_card = self.get_top_card()

        if not self.is_valid_play(card_to_play):
            if self.pending_draw_cards > 0:
                return (f"Bạn đang bị bắt rút {self.pending_draw_cards} lá. "
                        f"Bạn phải đánh lá 'Draw Two' hoặc 'Wild Draw Four' tương ứng nếu có, hoặc dùng lệnh `/draw_card`."
                        f" (Lá trên cùng: {str(top_card)})")
            else:
                return f"Lá `{str(card_to_play)}` không hợp lệ. Vui lòng đánh lá bài cùng màu hoặc cùng số/loại với '{str(top_card)}'."

        if card_to_play.is_wild():
            if not chosen_color or chosen_color not in ["red", "green", "blue", "yellow"]:
                return "Bạn phải chọn màu cho lá Wild! Vui lòng dùng tham số `color_choice` khi dùng `/play` (red, green, blue, yellow)."
            self.current_color_choice = chosen_color
        else:
            self.current_color_choice = None

        player.hand.pop(card_index - 1)
        self.deck.place_on_discard_pile(card_to_play)

        if len(player.hand) != 1:
            player.said_uno = False

        response_message = f"**{player.discord_user_name}** đã đánh **{str(card_to_play)}**."
        response_message += f" (Lá `{str(card_to_play)}` đã được dùng và xóa khỏi tay bạn)."
        response_message += f" Hiện còn **{len(player.hand)}** lá trên tay."


        skip_next_player = False
        if card_to_play.value == "Skip":
            skip_next_player = True
            temp_next_player_index = (self.current_player_index + self.direction) % len(self.players)
            temp_next_player = self.players[temp_next_player_index]
            response_message += f"\n**{temp_next_player.discord_user_name} bị mất lượt!**"
        elif card_to_play.value == "Reverse":
            self.direction *= -1
            response_message += "\nHướng chơi đã bị Đảo ngược!"
            if len(self.players) == 2:
                skip_next_player = True
                temp_next_player_index = (self.current_player_index + self.direction) % len(self.players)
                temp_next_player = self.players[temp_next_player_index]
                response_message += f" Do đó, **{temp_next_player.discord_user_name} bị mất lượt!**"
        elif card_to_play.value == "Draw Two":
            self.pending_draw_cards += 2
            skip_next_player = True
            temp_next_player_index = (self.current_player_index + self.direction) % len(self.players)
            temp_next_player = self.players[temp_next_player_index]
            response_message += f"\n**{temp_next_player.discord_user_name} phải rút 2 lá!**"
        elif card_to_play.value == "Wild":
            response_message += f" Màu đã được đổi thành **{chosen_color.capitalize()}**."
        elif card_to_play.value == "Wild Draw Four":
            self.pending_draw_cards += 4
            skip_next_player = True
            response_message += f" Màu đã được đổi thành **{chosen_color.capitalize()}**."
            temp_next_player_index = (self.current_player_index + self.direction) % len(self.players)
            temp_next_player = self.players[temp_next_player_index]
            response_message += f" **{temp_next_player.discord_user_name} phải rút 4 lá!**"


        if not player.hand:
            response_message += f"\n🎉 **{player.discord_user_name} đã hết bài và THẮNG ván này!** 🎉"
            current_uno_game = None
            return response_message

        if len(player.hand) == 2:
            response_message += f"\n📢 **{player.discord_user_name} chỉ còn 2 lá bài!** Chuẩn bị gọi UNO! 📢"


        if len(player.hand) == 1 and not player.said_uno:
            penalty_cards = self.deck.draw_card(2)
            for card in penalty_cards:
                player.add_card(card)
            response_message += f"\n🚨 **{player.discord_user_name} QUÊN GỌI UNO! Rút thêm 2 lá!** 🚨"

            user = await bot.fetch_user(player.discord_user_id)
            if user.dm_channel is None:
                await user.create_dm()
            await user.dm_channel.send(f"Bạn đã quên gọi UNO! và bị phạt rút 2 lá. Bài mới của bạn:\n{player.get_hand_display()}")

        self.next_turn()
        if skip_next_player:
            self.next_turn()

        if current_uno_game:
            current_top_card = self.get_top_card()
            top_card_display = str(current_top_card)
            if current_top_card.is_wild() and self.current_color_choice:
                top_card_display += f" (Màu hiện tại: **{current_uno_game.current_color_choice.capitalize()}**)"

            response_message += f"\nLá bài trên cùng: **{top_card_display}**"

            next_player = self.get_current_player()
            if next_player:
                response_message += f"\nLượt của: **{next_player.discord_user_name}**."
                user = await bot.fetch_user(next_player.discord_user_id)
                if user.dm_channel is None:
                    await user.create_dm()
                await user.dm_channel.send(f"Đến lượt bạn! Bài của bạn:\n{next_player.get_hand_display()}")
            else:
                response_message += "\nKhông còn người chơi nào còn lại trong game."

        return response_message

    def next_turn(self):
        if len(self.players) == 0:
            return
        self.current_player_index = (self.current_player_index + self.direction) % len(self.players)

def is_host(interaction: discord.Interaction):
    global current_uno_game
    return current_uno_game and current_uno_game.host.discord_user_id == interaction.user.id

@bot.event
async def on_ready():
    print(f'Bot đã sẵn sàng! Đăng nhập với tên: {bot.user}')
    try:
        synced = await bot.tree.sync()
        print(f"Đã đồng bộ {len(synced)} lệnh(s) slash.")
    except Exception as e:
        print(f"Lỗi khi đồng bộ lệnh slash: {e}")

@bot.command(name="help")
async def custom_help(ctx: commands.Context):
    embed = discord.Embed(
        title="Trợ giúp Uno Bot",
        description="Chào bạn! Tôi là Uno Bot. Vui lòng sử dụng lệnh Slash Command: `/help_uno` để xem các tùy chọn hướng dẫn.",
        color=discord.Color.green()
    )
    embed.set_footer(text="Nếu bạn có bất kỳ câu hỏi nào, hãy liên hệ với người quản lý server.")
    await ctx.send(embed=embed)

def get_commands_guide_embed():
    embed = discord.Embed(
        title="Hướng dẫn lệnh Uno Bot",
        description="Dưới đây là danh sách các lệnh bạn có thể sử dụng để tương tác với Uno Bot:",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="🎮 Lệnh bắt đầu và tham gia game",
        value=(
            "`/start_uno` - Bắt đầu một ván bài Uno mới.\n"
            "`/join_uno` - Tham gia vào ván bài Uno đang chờ.\n"
            "`/deal_uno` - (Chỉ Host) Chia bài và bắt đầu ván đấu."
        ),
        inline=False
    )
    embed.add_field(
        name="🃏 Lệnh trong game",
        value=(
            "`/hand` - Xem các lá bài trên tay của bạn (hiển thị riêng tư).\n"
            "`/play <index> [color]` - Đánh một lá bài. `<index>` là số thứ tự của bài trên tay (từ 1). `[color]` là màu bạn chọn nếu đánh lá Wild (red/green/blue/yellow).\n"
            "`/draw_card` - Rút một lá bài từ bộ bài.\n"
            "`/uno` - Gọi UNO! khi bạn chỉ còn 1 lá bài.\n"
            "`/forfeit_uno` - Rời khỏi ván Uno hiện tại và bỏ cuộc."
        ),
        inline=False
    )
    embed.add_field(
        name="⛔ Lệnh kết thúc/quản lý game",
        value=(
            "`/end_uno` - Kết thúc ván bài Uno hiện tại (chỉ Host).\n"
            "`/pause_uno` - Tạm dừng ván Uno hiện tại (chỉ Host).\n"
            "`/resume_uno` - Tiếp tục ván Uno đã tạm dừng (chỉ Host)."
        ),
        inline=False
    )
    embed.add_field(
        name="📊 Lệnh thông tin Bot",
        value=(
            "`/server_info` - Hiển thị các máy chủ bot đang tham gia.\n"
            "`/bot_stats` - Hiển thị số liệu thống kê tổng quan về bot (số máy chủ, tổng người dùng).\n"
            "`/sync` - Đồng bộ hóa các lệnh slash."
        ),
        inline=False
    )
    embed.add_field(
        name="💡 Mẹo:",
        value=(
            "• Sử dụng `/hand` để xem số thứ tự của các lá bài trước khi dùng `/play`.\n"
            "• Các lá bài Wild (như Wild, Wild Draw Four) cho phép bạn chọn màu mới cho vòng đấu.\n"
            "• Nếu bạn bị bắt rút bài (do Draw Two/Wild Draw Four), bạn phải đánh lá cùng loại hoặc dùng lệnh `/draw_card` để chồng bài."
        ),
        inline=False
    )
    embed.set_footer(text="Chúc bạn chơi Uno vui vẻ!")
    return embed

def get_how_to_play_uno_embed():
    embed = discord.Embed(
        title="Hướng dẫn cách chơi Uno",
        description="**Mục tiêu:** Trở thành người chơi đầu tiên hết bài trên tay.\n\n"
                              "**1. Chia bài:** Mỗi người chơi được chia 7 lá bài. Một lá bài được lật ngửa để bắt đầu chồng bài bỏ (discard pile).",
        color=discord.Color.orange()
    )
    embed.add_field(
        name="2. Lượt chơi:",
        value=(
            "• Người chơi sẽ thay phiên nhau đánh bài theo chiều kim đồng hồ (hoặc ngược lại nếu có lá Reverse).\n"
            "• Bạn phải đánh một lá bài có **cùng màu** hoặc **cùng số/loại** với lá bài trên cùng của chồng bài bỏ.\n"
            "• **Ví dụ:** Nếu lá trên cùng là Red 7, bạn có thể đánh bất kỳ lá bài Đỏ nào HOẶC bất kỳ lá bài 7 nào."
        ),
        inline=False
    )
    embed.add_field(
        name="3. Rút bài:",
        value=(
            "• Nếu bạn không có lá bài hợp lệ để đánh, bạn phải rút một lá bài từ bộ bài.\n"
            "• Nếu lá bài vừa rút có thể đánh được, bạn có thể đánh nó ngay lập tức. Nếu không, lượt chơi chuyển sang người tiếp theo.\n"
            "• Bạn cũng có thể chọn rút bài ngay cả khi có bài hợp lệ để đánh, nhưng sau đó bạn phải đánh lá bài vừa rút (nếu hợp lệ) hoặc bỏ lượt."
        ),
        inline=False
    )
    embed.add_field(
        name="4. Các lá bài hành động đặc biệt:",
        value=(
            "• **Skip (Bỏ lượt):** Người chơi tiếp theo bị mất lượt.\n"
            "• **Reverse (Đảo chiều):** Thay đổi hướng chơi. Với 2 người chơi, lá này hoạt động như lá Skip.\n"
            "• **Draw Two (+2):** Người chơi tiếp theo phải rút 2 lá và bị mất lượt.\n"
            "• **Wild (Đổi màu):** Có thể đánh bất cứ lúc nào. Người chơi đánh lá này chọn màu tiếp theo (Đỏ, Xanh lá, Xanh dương, Vàng).\n"
            "• **Wild Draw Four (+4 & Đổi màu):** Có thể đánh bất cứ lúc nào, nhưng chỉ khi bạn KHÔNG có lá bài hợp lệ nào khác để đánh. Người chơi tiếp theo phải rút 4 lá và bị mất lượt. Người đánh lá này chọn màu tiếp theo."
        ),
        inline=False
    )
    embed.add_field(
        name="5. Gọi Uno!:",
        value=(
            "• Khi bạn còn **1 lá bài** trên tay, bạn phải gọi **\"UNO!\"** (dùng lệnh `/uno`).\n"
            "• Nếu bạn quên gọi UNO! và bị người chơi khác phát hiện trước khi người tiếp theo đánh bài, bạn sẽ bị phạt rút thêm 2 lá bài."
        ),
        inline=False
    )
    embed.add_field(
        name="6. Thắng cuộc:",
        value="• Người chơi đầu tiên hết bài trên tay sẽ thắng ván đấu.",
        inline=False
    )
    embed.set_footer(text="Luật Uno có thể có một số biến thể, đây là luật cơ bản.")
    return embed

class HelpUnoDropdownView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.message = None

        option1 = discord.SelectOption(label="Hướng dẫn Lệnh Bot", value="commands_guide", description="Xem danh sách các lệnh có thể sử dụng")
        option2 = discord.SelectOption(label="Cách chơi Uno", value="how_to_play_uno", description="Tìm hiểu luật chơi Uno cơ bản")

        select = discord.ui.Select(
            placeholder="Chọn một tùy chọn...",
            options=[option1, option2],
            custom_id="help_uno_select_menu"
        )
        self.add_item(select)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.select(custom_id="help_uno_select_menu")
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        async with interaction.response.defer(ephemeral=True):
            selected_value = select.values[0]

            if not self.message:
                if selected_value == "commands_guide":
                    await interaction.followup.send(embed=get_commands_guide_embed(), ephemeral=True)
                elif selected_value == "how_to_play_uno":
                    await interaction.followup.send(embed=get_how_to_play_uno_embed(), ephemeral=True)
                return

            try:
                if selected_value == "commands_guide":
                    await self.message.edit(embed=get_commands_guide_embed(), view=self)
                elif selected_value == "how_to_play_uno":
                    await self.message.edit(embed=get_how_to_play_uno_embed(), view=self)
            except discord.HTTPException:
                if selected_value == "commands_guide":
                    await interaction.followup.send(embed=get_commands_guide_embed(), ephemeral=True)
                elif selected_value == "how_to_play_uno":
                    await interaction.followup.send(embed=get_how_to_play_uno_embed(), ephemeral=True)

@bot.tree.command(name="commands_list", description="Hiển thị danh sách các lệnh Uno Bot.")
async def commands_list_command(interaction: discord.Interaction):
    async with interaction.response.defer(ephemeral=True):
        await interaction.followup.send(embed=get_commands_guide_embed(), ephemeral=True)

@bot.tree.command(name="help_uno", description="Hiển thị tùy chọn hướng dẫn lệnh hoặc cách chơi Uno.")
async def help_uno_command(interaction: discord.Interaction):
    view = HelpUnoDropdownView()
    async with interaction.response.defer(ephemeral=True):
        message = await interaction.followup.send(
            embed=get_commands_guide_embed(),
            view=view,
            ephemeral=True
        )
        view.message = message

@bot.tree.command(name="start_uno", description="Bắt đầu một ván bài Uno mới!")
async def start_uno_command(interaction: discord.Interaction):
    global current_uno_game

    if current_uno_game and current_uno_game.game_started:
        await interaction.response.send_message("Một ván Uno đang diễn ra rồi. Hãy chờ đến khi nó kết thúc hoặc dùng `/end_uno` để kết thúc ván hiện tại.", ephemeral=True)
        return

    current_uno_game = UnoGame(interaction.user.id, interaction.user.display_name, interaction.channel_id)

    await interaction.response.send_message(
        f"**Uno mới đã được khởi tạo!** Người chơi: {interaction.user.display_name}\n"
        f"Các người chơi khác có thể dùng `/join_uno` để tham gia."
    )

@bot.tree.command(name="join_uno", description="Tham gia vào ván bài Uno hiện tại.")
async def join_uno_command(interaction: discord.Interaction):
    global current_uno_game
    if not current_uno_game or current_uno_game.game_started:
        await interaction.response.send_message("Không có ván Uno nào đang chờ người chơi hoặc ván đã bắt đầu. Dùng `/start_uno` để bắt đầu ván mới.", ephemeral=True)
        return

    if current_uno_game.add_player(interaction.user.id, interaction.user.display_name):
        players_list = ", ".join([p.discord_user_name for p in current_uno_game.players])
        await interaction.response.send_message(f"**{interaction.user.display_name} đã tham gia ván Uno!**\nNgười chơi hiện tại: {players_list}")
    else:
        await interaction.response.send_message("Bạn đã tham gia ván này rồi hoặc số lượng người chơi đã đầy (tối đa 10 người).", ephemeral=True)

@bot.tree.command(name="deal_uno", description="Bắt đầu chia bài và chơi Uno (chỉ Host).")
@app_commands.check(is_host)
async def deal_uno_command(interaction: discord.Interaction):
    global current_uno_game
    if not current_uno_game:
        await interaction.response.send_message("Không có ván Uno nào được tạo. Dùng `/start_uno` để bắt đầu.", ephemeral=True)
        return

    if interaction.user.id != current_uno_game.host.discord_user_id:
        await interaction.response.send_message("Chỉ Host mới có thể chia bài.", ephemeral=True)
        return

    if current_uno_game.game_started:
        await interaction.response.send_message("Ván bài đã bắt đầu rồi.", ephemeral=True)
        return

    async with interaction.response.defer():
        success, message = current_uno_game.start_game()
        if success:
            current_player = current_uno_game.get_current_player()
            top_card = current_uno_game.get_top_card()

            response_text = (
                f"**Bài đã được chia! Ván Uno bắt đầu!**\n"
                f"Lá bài trên cùng: **{str(top_card)}**"
            )
            if message:
                response_text += f"\n{message}"

            if current_player:
                response_text += f"\nLượt của: **{current_player.discord_user_name}**."
            else:
                response_text += "\nKhông có người chơi nào để bắt đầu lượt."

            await interaction.followup.send(response_text)

            for player in current_uno_game.players:
                user = await bot.fetch_user(player.discord_user_id)
                if user.dm_channel is None:
                    await user.create_dm()
                await user.dm_channel.send(f"Bài của bạn:\n{player.get_hand_display()}")
        else:
            await interaction.followup.send(message)

@bot.tree.command(name="hand", description="Kiểm tra bài trên tay của bạn.")
async def hand_command(interaction: discord.Interaction):
    global current_uno_game
    if not current_uno_game or not current_uno_game.game_started:
        await interaction.response.send_message("Hiện không có ván Uno nào đang diễn ra.", ephemeral=True)
        return

    if current_uno_game.is_paused:
        await interaction.response.send_message("Game đang tạm dừng, không thể xem bài.", ephemeral=True)
        return

    player = next((p for p in current_uno_game.players if p.discord_user_id == interaction.user.id), None)
    if player:
        await interaction.response.send_message(f"Bài của bạn:\n{player.get_hand_display()}", ephemeral=True)
    else:
        await interaction.response.send_message("Bạn không phải là người chơi trong ván này.", ephemeral=True)

@bot.tree.command(name="play", description="Đánh một lá bài Uno.")
@app_commands.describe(
    index="Số thứ tự của lá bài bạn muốn đánh (bắt đầu từ 1, xem bằng /hand)",
    color_choice="Màu bạn chọn nếu đánh lá Wild (red, green, blue, yellow)"
)
@app_commands.choices(
    color_choice=[
        app_commands.Choice(name="Red", value="red"),
        app_commands.Choice(name="Green", value="green"),
        app_commands.Choice(name="Blue", value="blue"),
        app_commands.Choice(name="Yellow", value="yellow"),
    ]
)
async def play_card_command(interaction: discord.Interaction, index: int, color_choice: app_commands.Choice[str] = None):
    global current_uno_game
    if not current_uno_game or not current_uno_game.game_started:
        await interaction.response.send_message("Hiện không có ván Uno nào đang diễn ra.", ephemeral=True)
        return

    async with interaction.response.defer():
        chosen_color_value = color_choice.value if color_choice else None

        response_message = await current_uno_game.play_card(
            interaction, interaction.user.id, index, chosen_color_value
        )

        await interaction.followup.send(response_message)

@bot.tree.command(name="draw_card", description="Rút bài từ bộ bài.")
async def draw_card_command(interaction: discord.Interaction):
    global current_uno_game
    if not current_uno_game or not current_uno_game.game_started:
        await interaction.response.send_message("Hiện không có ván Uno nào đang diễn ra.", ephemeral=True)
        return

    if current_uno_game.is_paused:
        await interaction.response.send_message("Game đang tạm dừng. Vui lòng đợi host tiếp tục game.", ephemeral=True)
        return

    player = next((p for p in current_uno_game.players if p.discord_user_id == interaction.user.id), None)
    if not player:
        await interaction.response.send_message("Bạn không phải là người chơi trong ván này.", ephemeral=True)
        return

    if player != current_uno_game.get_current_player():
        await interaction.response.send_message("Chưa đến lượt của bạn!", ephemeral=True)
        return

    async with interaction.response.defer():
        if current_uno_game.pending_draw_cards > 0:
            drawn_cards = current_uno_game.deck.draw_card(current_uno_game.pending_draw_cards)
            num_to_draw = current_uno_game.pending_draw_cards
            current_uno_game.pending_draw_cards = 0

            if not drawn_cards:
                await interaction.followup.send("Bộ bài đã hết và không thể rút thêm bài.")
                return

            for card in drawn_cards:
                player.add_card(card)

            current_uno_game.next_turn()

            drawn_str = ", ".join([str(c) for c in drawn_cards])
            response_message = f"**{player.discord_user_name}** đã rút **{num_to_draw}** lá bài: {drawn_str}."
            response_message += f"\nBạn hiện có **{len(player.hand)}** lá bài."

            top_card = current_uno_game.get_top_card()
            top_card_display = str(top_card)
            if top_card.is_wild() and current_uno_game.current_color_choice:
                top_card_display += f" (Màu hiện tại: **{current_uno_game.current_color_choice.capitalize()}**)"

            response_message += f"\nLá bài trên cùng: **{top_card_display}**"
            next_player = current_uno_game.get_current_player()
            if next_player:
                response_message += f"\nLượt của: **{next_player.discord_user_name}**."
                user = await bot.fetch_user(next_player.discord_user_id)
                if user.dm_channel is None:
                    await user.create_dm()
                await user.dm_channel.send(f"Đến lượt bạn! Bạn đang bị bắt rút **{current_uno_game.pending_draw_cards}** lá bài. Hãy dùng `/draw_card` hoặc đánh lá bài tương ứng (Draw Two/Wild Draw Four) để chồng bài.")
            else:
                response_message += "\nKhông còn người chơi nào trong game."

            await interaction.followup.send(response_message)
        else:
            drawn_card = current_uno_game.deck.draw_card(1)
            if not drawn_card:
                await interaction.followup.send("Bộ bài đã hết và không thể rút thêm bài.")
                return

            player.add_card(drawn_card[0])
            response_message = f"**{player.discord_user_name}** đã rút **{str(drawn_card[0])}**."
            response_message += f"\nBạn hiện có **{len(player.hand)}** lá bài."

            user = await bot.fetch_user(player.discord_user_id)
            if user.dm_channel is None:
                await user.create_dm()
            await user.dm_channel.send(f"Bài mới của bạn:\n{player.get_hand_display()}")

            top_card = current_uno_game.get_top_card()
            if current_uno_game.is_valid_play(drawn_card[0]):
                response_message += f"\nBạn có thể đánh lá **{str(drawn_card[0])}** vừa rút bằng cách dùng `/play {len(player.hand)}` hoặc bạn có thể bỏ lượt."
                response_message += f"\nLá bài trên cùng: **{str(top_card)}**"
                next_player = current_uno_game.get_current_player()
                if next_player:
                    response_message += f"\nLượt của: **{next_player.discord_user_name}**."
            else:
                current_uno_game.next_turn()
                next_player = current_uno_game.get_current_player()
                if next_player:
                    response_message += f"\nLá bài vừa rút không thể đánh được. Lượt chơi đã chuyển sang **{next_player.discord_user_name}**."
                else:
                    response_message += "\nLá bài vừa rút không thể đánh được. Không còn người chơi nào trong game."

                top_card_display = str(top_card)
                if top_card.is_wild() and current_uno_game.current_color_choice:
                    top_card_display += f" (Màu hiện tại: **{current_uno_game.current_color_choice.capitalize()}**)"
                response_message += f"\nLá bài trên cùng: **{top_card_display}**"

            await interaction.followup.send(response_message)

@bot.tree.command(name="uno", description="Gọi UNO! khi bạn chỉ còn 1 lá bài.")
async def uno_command(interaction: discord.Interaction):
    global current_uno_game
    if not current_uno_game or not current_uno_game.game_started:
        await interaction.response.send_message("Hiện không có ván Uno nào đang diễn ra.", ephemeral=True)
        return

    if current_uno_game.is_paused:
        await interaction.response.send_message("Game đang tạm dừng. Vui lòng đợi host tiếp tục game.", ephemeral=True)
        return

    player = next((p for p in current_uno_game.players if p.discord_user_id == interaction.user.id), None)
    if not player:
        await interaction.response.send_message("Bạn không phải là người chơi trong ván này.", ephemeral=True)
        return

    if len(player.hand) == 1:
        player.said_uno = True
        await interaction.response.send_message(f"**{player.discord_user_name} đã gọi UNO!**")
    else:
        await interaction.response.send_message("Bạn chỉ có thể gọi UNO! khi còn 1 lá bài trên tay.", ephemeral=True)

@bot.tree.command(name="forfeit_uno", description="Rời khỏi ván Uno hiện tại và bỏ cuộc.")
async def forfeit_uno_command(interaction: discord.Interaction):
    global current_uno_game
    if not current_uno_game:
        await interaction.response.send_message("Hiện không có ván Uno nào đang diễn ra để bỏ cuộc.", ephemeral=True)
        return

    player = next((p for p in current_uno_game.players if p.discord_user_id == interaction.user.id), None)
    if not player:
        await interaction.response.send_message("Bạn không phải là người chơi trong ván này.", ephemeral=True)
        return

    result = current_uno_game.remove_player(interaction.user.id)

    if result == "host_forfeited":
        await interaction.response.send_message(f"**{interaction.user.display_name}** (Host) đã bỏ cuộc. Ván đấu Uno kết thúc.")
        current_uno_game = None
    elif result == "success":
        if len(current_uno_game.players) == 0:
            await interaction.response.send_message(f"**{interaction.user.display_name}** đã bỏ cuộc. Không còn người chơi nào trong game, ván đấu kết thúc.")
            current_uno_game = None
        else:
            players_list = ", ".join([p.discord_user_name for p in current_uno_game.players])
            next_player_info = ""
            if current_uno_game.game_started:
                next_player = current_uno_game.get_current_player()
                if next_player:
                    next_player_info = f"\nLượt của: **{next_player.discord_user_name}**."
                else:
                    next_player_info = "\nKhông còn người chơi nào còn lại trong game."
            await interaction.response.send_message(f"**{interaction.user.display_name}** đã bỏ cuộc. Người chơi còn lại: {players_list}.{next_player_info}")
    elif result == "no_players_left":
        await interaction.response.send_message(f"**{interaction.user.display_name}** đã bỏ cuộc. Không còn người chơi nào trong game, ván đấu kết thúc.")
        current_uno_game = None
    else:
        await interaction.response.send_message("Bạn không phải là người chơi trong ván này.", ephemeral=True)


@bot.tree.command(name="end_uno", description="Kết thúc ván Uno hiện tại (chỉ Host).")
@app_commands.check(is_host)
async def end_uno_command(interaction: discord.Interaction):
    global current_uno_game
    if not current_uno_game:
        await interaction.response.send_message("Không có ván Uno nào đang diễn ra.", ephemeral=True)
        return

    await interaction.response.send_message("Ván Uno đã kết thúc theo yêu cầu của Host.")
    current_uno_game = None

@bot.tree.command(name="pause_uno", description="Tạm dừng ván Uno hiện tại (chỉ Host).")
@app_commands.check(is_host)
async def pause_uno_command(interaction: discord.Interaction):
    global current_uno_game
    if not current_uno_game or not current_uno_game.game_started:
        await interaction.response.send_message("Không có ván Uno nào đang diễn ra hoặc chưa bắt đầu.", ephemeral=True)
        return

    if current_uno_game.is_paused:
        await interaction.response.send_message("Ván Uno đã được tạm dừng rồi.", ephemeral=True)
        return
    current_uno_game.is_paused = True
    await interaction.response.send_message("Ván Uno đã được tạm dừng. Dùng `/resume_uno` để tiếp tục.")

@bot.tree.command(name="resume_uno", description="Tiếp tục ván Uno đã tạm dừng (chỉ Host).")
@app_commands.check(is_host)
async def resume_uno_command(interaction: discord.Interaction):
    global current_uno_game
    if not current_uno_game or not current_uno_game.game_started:
        await interaction.response.send_message("Không có ván Uno nào đang diễn ra hoặc chưa bắt đầu.", ephemeral=True)
        return

    if not current_uno_game.is_paused:
        await interaction.response.send_message("Ván Uno không bị tạm dừng.", ephemeral=True)
        return
    current_uno_game.is_paused = False
    await interaction.response.send_message("Ván Uno đã được tiếp tục!")
    current_player = current_uno_game.get_current_player()
    top_card_display = str(current_uno_game.get_top_card())
    if current_uno_game.get_top_card().is_wild() and current_uno_game.current_color_choice:
        top_card_display += f" (Màu hiện tại: **{current_uno_game.current_color_choice.capitalize()}**)"
    if current_player:
        await interaction.followup.send(f"Lá bài trên cùng: **{top_card_display}**\nLượt của: **{current_player.discord_user_name}**.")
    else:
        await interaction.followup.send(f"Lá bài trên cùng: **{top_card_display}**\nKhông còn người chơi nào trong game.")

@bot.tree.command(name="kick_player", description="Kick một người chơi khỏi game Uno (chỉ Host).")
@app_commands.describe(
    target_player="Người chơi bạn muốn kick."
)
@app_commands.check(is_host)
async def kick_player_command(interaction: discord.Interaction, target_player: discord.Member):
    global current_uno_game
    if not current_uno_game:
        await interaction.response.send_message("Không có ván Uno nào đang diễn ra.", ephemeral=True)
        return

    if target_player.id == current_uno_game.host.discord_user_id:
        await interaction.response.send_message("Bạn không thể tự kick chính mình (Host). Nếu bạn muốn kết thúc game, hãy dùng `/end_uno`.", ephemeral=True)
        return

    result = current_uno_game.remove_player(target_player.id)

    if result == "success":
        if len(current_uno_game.players) == 0:
            await interaction.response.send_message(f"**{target_player.display_name}** đã bị kick. Không còn người chơi nào trong game, ván đấu kết thúc.")
            current_uno_game = None
        else:
            players_list = ", ".join([p.discord_user_name for p in current_uno_game.players])
            next_player_info = ""
            if current_uno_game.game_started:
                next_player = current_uno_game.get_current_player()
                if next_player:
                    next_player_info = f"\nLượt của: **{next_player.discord_user_name}**."
                else:
                    next_player_info = "\nKhông còn người chơi nào còn lại trong game."
            await interaction.response.send_message(f"**{target_player.display_name}** đã bị kick khỏi ván. Người chơi còn lại: {players_list}.{next_player_info}")
    elif result == "not_found":
        await interaction.response.send_message(f"**{target_player.display_name}** không phải là người chơi trong ván này.", ephemeral=True)
    elif result == "no_players_left":
        await interaction.response.send_message(f"**{target_player.display_name}** đã bị kick. Không còn người chơi nào trong game, ván đấu kết thúc.")
        current_uno_game = None

@bot.tree.command(name="add_cards_to_player", description="Thêm bài vào tay một người chơi (chỉ Host).")
@app_commands.describe(
    target_player="Người chơi bạn muốn thêm bài.",
    num_cards="Số lượng bài muốn thêm."
)
@app_commands.check(is_host)
async def add_cards_to_player_command(interaction: discord.Interaction, target_player: discord.Member, num_cards: int):
    global current_uno_game
    if not current_uno_game or not current_uno_game.game_started:
        await interaction.response.send_message("Không có ván Uno nào đang diễn ra.", ephemeral=True)
        return

    uno_player_target = next((p for p in current_uno_game.players if p.discord_user_id == target_player.id), None)
    if not uno_player_target:
        await interaction.response.send_message(f"{target_player.display_name} không phải là người chơi trong ván này.", ephemeral=True)
        return

    if num_cards <= 0:
        await interaction.response.send_message("Số lượng bài thêm phải lớn hơn 0.", ephemeral=True)
        return

    drawn_cards = current_uno_game.deck.draw_card(num_cards)
    if not drawn_cards:
        await interaction.response.send_message("Bộ bài đã hết, không thể thêm bài.", ephemeral=True)
        return

    for card in drawn_cards:
        uno_player_target.add_card(card)

    drawn_str = ", ".join([str(c) for c in drawn_cards])
    await interaction.response.send_message(f"Đã thêm **{len(drawn_cards)}** lá bài vào tay **{target_player.display_name}**.")

    try:
        user_dm = await bot.fetch_user(target_player.id)
        if user_dm.dm_channel is None:
            await user_dm.create_dm()
        await user_dm.dm_channel.send(
            f"Bạn đã được thêm {num_cards} lá bài: **{drawn_str}**.\n"
            f"Bài của bạn:\n{uno_player_target.get_hand_display()}"
        )
    except discord.Forbidden:
        await interaction.followup.send(f"Không thể gửi DM cho {target_player.display_name}. Có thể họ đã tắt DM.", ephemeral=True)


@bot.tree.command(name="sync", description="Đồng bộ hóa các lệnh slash.")
async def sync_commands(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        synced = await bot.tree.sync()
        await interaction.followup.send(f"Đã đồng bộ {len(synced)} lệnh(s) slash.", ephemeral=True)
        print(f"Đã đồng bộ {len(synced)} lệnh(s) slash bởi lệnh /sync.")
    except Exception as e:
        await interaction.followup.send(f"Lỗi khi đồng bộ lệnh slash: {e}", ephemeral=True)
        print(f"Lỗi khi đồng bộ lệnh slash bằng /sync: {e}")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    if isinstance(error, app_commands.CheckFailure):
        if interaction.command.name in ["deal_uno", "end_uno", "pause_uno", "resume_uno", "kick_player", "add_cards_to_player"]:
            await interaction.followup.send("Bạn không có quyền sử dụng lệnh này (chỉ dành cho Host).", ephemeral=True)
        else:
             await interaction.followup.send(f"Bạn không có quyền sử dụng lệnh `{interaction.command.name}` này.", ephemeral=True)
    elif isinstance(error, app_commands.CommandOnCooldown):
        await interaction.followup.send(f"Lệnh này đang trong thời gian hồi chiêu. Vui lòng thử lại sau {error.retry_after:.2f} giây.", ephemeral=True)
    elif isinstance(error, app_commands.MissingRequiredArgument):
        await interaction.followup.send(f"Thiếu tham số: `{error.param.name}`. Vui lòng kiểm tra lại cách dùng lệnh.", ephemeral=True)
    else:
        print(f"Lỗi không xác định trong lệnh slash {interaction.command.name}: {error}")
        await interaction.followup.send("Đã xảy ra lỗi không mong muốn khi thực hiện lệnh. Vui lòng thử lại sau.", ephemeral=True)

load_dotenv()
discord_token = os.getenv("DISCORD_BOT_TOKEN")

if not discord_token:
    print("Lỗi: Không tìm thấy DISCORD_BOT_TOKEN trong file .env")
    exit()

bot.run(discord_token)