import discord
from discord.ext import commands
from discord import app_commands, Interaction, Member, Guild, Webhook, TextChannel, CategoryChannel, AuditLogAction, VoiceChannel, StageChannel
import aiohttp
from zoneinfo import ZoneInfo
import datetime
import json
import aiosqlite
import io
from typing import Union
from emojis import *
DB_PATH = "db/logging_database.db"
def get_indian_time():
    return datetime.datetime.now(ZoneInfo("Asia/Kolkata"))
class LoggingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.guild_configs = {}
        self.session = None
        self.logging_color = 0xFF5858
        self.log_channel_details = {
            "system": {"name": "》》system_logs『💻』", "emoji": "💻"},
            "member": {"name": "》》member_logs『👤』", "emoji": "👤"},
            "message": {"name": "》》message_logs『💬』", "emoji": "💬"},
            "voice": {"name": "》》voice_logs『🔊』", "emoji": "🔊"},
            "moderation": {"name": "》》moderation_logs『🔨』", "emoji": "🔨"},
            "channel": {"name": "》》channel_logs『📩』", "emoji": "📩"},
            "server": {"name": "》》server_logs『🌐』", "emoji": "🌐"},
            "webhook": {"name": "》》webhook_logs『🔗』","emoji": "🔗"},
            "role": {"name": "》》role_logs『⚙️』","emoji": "⚙️"},
            "application": {"name": "》》application_logs『🤖』","emoji": "🤖"}
        }
        self.log_types = list(self.log_channel_details.keys())
        self.category_name = "✦────── 💬│Server_Logs ─────────✦"
        self.log_view_role_name = "log_view"
    async def cog_load(self):
        print("Logging Cog loaded.")
        self.session = aiohttp.ClientSession()
        await self.initialize_logging_db()
    async def cog_unload(self):
        print("Logging Cog unloaded.")
        if self.session:
            await self.session.close()
            self.session = None
    async def initialize_logging_db(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS logging_guild_configs (
                    guild_id INTEGER PRIMARY KEY,
                    config TEXT
                )
            ''')
            await db.commit()
    async def get_guild_config_async(self, guild_id: int):
        config_data = self.guild_configs.get(str(guild_id))
        if config_data:
            return config_data
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute('SELECT config FROM logging_guild_configs WHERE guild_id = ?', (guild_id,))
            result = await cursor.fetchone()
            if result:
                loaded_config = json.loads(result[0])
                self.guild_configs[str(guild_id)] = loaded_config
                return loaded_config
            else:
                default_config = {
                    "log_category_id": None,
                    "log_channel_ids": {},
                    "webhooks": {},
                    "logging_enabled": True
                }
                await db.execute('INSERT INTO logging_guild_configs (guild_id, config) VALUES (?, ?)',
                                 (guild_id, json.dumps(default_config)))
                await db.commit()
                self.guild_configs[str(guild_id)] = default_config
                return default_config
    async def update_guild_config_async(self, guild_id: int, config_data: dict):
        self.guild_configs[str(guild_id)] = config_data
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR REPLACE INTO logging_guild_configs (guild_id, config) VALUES (?, ?)',
                             (guild_id, json.dumps(config_data)))
            await db.commit()
    async def send_embed_files(self, guild: Guild, log_type: str, embed: discord.Embed, files: list[discord.File] = None):
        if not guild or not self.session:
            return
        guild_id = guild.id
        config = await self.get_guild_config_async(guild_id)
        if not config.get("logging_enabled"):
            return
        log_channel_id = config.get("log_channel_ids", {}).get(log_type)
        if not log_channel_id:
            return
        log_channel = guild.get_channel(log_channel_id)
        if not log_channel:
            return
        webhook_url = config.get("webhooks", {}).get(log_type)
        webhook = None
        if webhook_url:
            try:
                webhook = Webhook.from_url(webhook_url, session=self.session)
            except discord.errors.InvalidWebhook:
                print(f"Invalid webhook URL for {log_type} in guild {guild_id}. Attempting to re-create.")
                webhook = await self.create_and_save_webhook_for_channel(guild, log_type, log_channel)
            except Exception as e:
                print(f"Error setting up webhook from URL for {log_type}: {e}")
        if not webhook:
            print(f"Webhook for {log_type} not found in config or failed to initialize. Attempting to create a new one.")
            webhook = await self.create_and_save_webhook_for_channel(guild, log_type, log_channel)
            if not webhook:
                print(f"Failed to create webhook for {log_type} in guild {guild_id}. Returning.")
                return
        try:
            await webhook.send(
                embed=embed,
                files=files,
                username=self.bot.user.name,
                avatar_url=self.bot.user.avatar.url if self.bot.user.avatar else None
            )
        except discord.Forbidden:
            print(f"Missing permissions to send messages to webhook for {log_type} in guild {guild_id}.")
        except discord.errors.NotFound:
            print(f"Webhook for {log_type} in guild {guild_id} not found during send (404). Attempting to re-create and resend.")
            config["webhooks"][log_type] = None
            await self.update_guild_config_async(guild_id, config)
            new_webhook = await self.create_and_save_webhook_for_channel(guild, log_type, log_channel)
            if new_webhook:
                try:
                    await new_webhook.send(
                        embed=embed,
                        files=files,
                        username=self.bot.user.name,
                        avatar_url=self.bot.user.avatar.url if self.bot.user.avatar else None
                    )
                    print(f"Message successfully resent with new webhook for {log_type} in guild {guild_id}.")
                except Exception as resend_e:
                    print(f"Error resending message with new webhook for {log_type}: {resend_e}")
            else:
                print(f"Failed to re-create webhook for {log_type} and resend message in guild {guild_id}.")
        except Exception as e:
            print(f"Error sending webhook message for {log_type}: {e}")

    async def send_embed(self, guild: Guild, log_type: str, embed: discord.Embed):
        if not guild or not self.session:
            return
        guild_id = guild.id
        config = await self.get_guild_config_async(guild_id)
        if not config.get("logging_enabled"):
            return
        log_channel_id = config.get("log_channel_ids", {}).get(log_type)
        if not log_channel_id:
            return
        log_channel = guild.get_channel(log_channel_id)
        if not log_channel:
            return
        webhook_url = config.get("webhooks", {}).get(log_type)
        webhook = None
        if webhook_url:
            try:
                webhook = Webhook.from_url(webhook_url, session=self.session)
            except discord.errors.InvalidWebhook:
                print(f"Invalid webhook URL for {log_type} in guild {guild_id}. Attempting to re-create.")
                webhook = await self.create_and_save_webhook_for_channel(guild, log_type, log_channel)
            except Exception as e:
                print(f"Error setting up webhook from URL for {log_type}: {e}")
        if not webhook:
            print(f"Webhook for {log_type} not found in config or failed to initialize. Attempting to create a new one.")
            webhook = await self.create_and_save_webhook_for_channel(guild, log_type, log_channel)
            if not webhook:
                print(f"Failed to create webhook for {log_type} in guild {guild_id}. Returning.")
                return
        try:
            await webhook.send(
                embed=embed,
                username=self.bot.user.name,
                avatar_url=self.bot.user.avatar.url if self.bot.user.avatar else None
            )
        except discord.Forbidden:
            print(f"Missing permissions to send messages to webhook for {log_type} in guild {guild_id}.")
        except discord.errors.NotFound:
            print(f"Webhook for {log_type} in guild {guild_id} not found during send (404). Attempting to re-create and resend.")
            config["webhooks"][log_type] = None
            await self.update_guild_config_async(guild_id, config) 
            new_webhook = await self.create_and_save_webhook_for_channel(guild, log_type, log_channel)
            if new_webhook:
                try:
                    await new_webhook.send(
                        embed=embed,
                        username=self.bot.user.name,
                        avatar_url=self.bot.user.avatar.url if self.bot.user.avatar else None
                    )
                    print(f"Message successfully resent with new webhook for {log_type} in guild {guild_id}.")
                except Exception as resend_e:
                    print(f"Error resending message with new webhook for {log_type}: {resend_e}")
            else:
                print(f"Failed to re-create webhook for {log_type} and resend message in guild {guild_id}.")
        except Exception as e:
            print(f"Error sending webhook message for {log_type}: {e}")

    async def create_and_save_webhook_for_channel(self, guild: Guild, log_type: str, channel: TextChannel) -> Webhook | None:
        config = await self.get_guild_config_async(guild.id)
        if not config:
            return None
        try:
            bot_avatar_url = self.bot.user.avatar.url if self.bot.user.avatar else None
            webhook_name = f"{self.bot.user.name} {log_type.replace('_', ' ').title()} Logs"
            webhook = await channel.create_webhook(
                name=webhook_name,
                avatar=await self.bot.user.avatar.read() if bot_avatar_url else None,
                reason=f"For {log_type} logging by {self.bot.user.name}"
            )
            config["webhooks"][log_type] = webhook.url
            await self.update_guild_config_async(guild.id, config)
            return webhook
        except discord.Forbidden:
            print(f"Missing 'Manage Webhooks' permission in {channel.mention} to set up {log_type} logging webhooks for guild {guild.id}.")
            return None
        except Exception as e:
            print(f"Error creating webhook for {log_type} in guild {guild.id}: {e}")
            return None

    logging_group = app_commands.Group(name="logging", description="Manage logging in the server.", default_permissions=discord.Permissions(administrator=True))
    @logging_group.command(name="setup_auto", description="Automatically sets up logging channels in a dedicated category.")
    async def logging_setup_auto(self, interaction: Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        everyone_role = guild.default_role
        log_view_role = discord.utils.get(guild.roles, name=self.log_view_role_name)
        if not log_view_role:
            try:
                log_view_role = await guild.create_role(name=self.log_view_role_name, reason="Role to view log channels")
            except discord.Forbidden:
                await interaction.followup.send("I don't have permissions to create roles. Please grant 'Manage Roles'.", ephemeral=True)
                return
            except Exception as e:
                await interaction.followup.send(f"Error creating log_view role: {e}", ephemeral=True)
                return
        overwrites = {
            everyone_role: discord.PermissionOverwrite(read_messages=False, send_messages=False),
            log_view_role: discord.PermissionOverwrite(read_messages=True, send_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        category = discord.utils.get(guild.categories, name=self.category_name)
        if not category:
            try:
                category = await guild.create_category(self.category_name, overwrites=overwrites, reason="Automatic logging setup")
            except discord.Forbidden:
                await interaction.followup.send("I don't have permissions to create categories or set permissions. Please grant 'Manage Channels' and 'Manage Permissions'.", ephemeral=True)
                return
            except Exception as e:
                await interaction.followup.send(f"Error creating logging category: {e}", ephemeral=True)
                return
        else:
            try:
                await category.edit(overwrites=overwrites, reason="Updating logging category permissions")
            except discord.Forbidden:
                await interaction.followup.send("I don't have permissions to edit category permissions. Please grant 'Manage Channels' and 'Manage Permissions'.", ephemeral=True)
                return
            except Exception as e:
                await interaction.followup.send(f"Error updating logging category permissions: {e}", ephemeral=True)
                return
        config = await self.get_guild_config_async(guild.id)
        config["log_category_id"] = category.id
        config["log_channel_ids"] = {}
        config["webhooks"] = {}
        created_channels_mentions = []
        for log_type, details in self.log_channel_details.items():
            channel_name = details["name"]
            existing_channel = discord.utils.get(category.text_channels, name=channel_name)
            channel_to_use = None
            if existing_channel:
                channel_to_use = existing_channel
            else:
                try:
                    channel_to_use = await guild.create_text_channel(
                        name=channel_name,
                        category=category,
                        topic=f"Logs for {channel_name.replace('》》','').replace('『','').replace('』','')[:-1].replace('_',' ').title()} events.",
                        reason=f"Automatic logging setup for {log_type}"
                    )
                except discord.Forbidden:
                    await interaction.followup.send(f"I don't have permissions to create channels in {category.mention}. Please grant 'Manage Channels'.", ephemeral=True)
                    return
                except Exception as e:
                    await interaction.followup.send(f"Error creating channel for {log_type}: {e}", ephemeral=True)
            if channel_to_use:
                config["log_channel_ids"][log_type] = channel_to_use.id
                created_channels_mentions.append(channel_to_use.mention)
                try:
                    webhook = await self.create_and_save_webhook_for_channel(guild, log_type, channel_to_use)
                    if not webhook:
                        await interaction.followup.send(f"Failed to create webhook for {log_type} in {channel_to_use.mention}. Check bot's 'Manage Webhooks' permission.", ephemeral=True)
                except Exception as e:
                    print(f"Failed to set up webhook for {log_type} in {channel_to_use.mention}: {e}")
                    await interaction.followup.send(f"Error creating webhook for {log_type} in {channel_to_use.mention}: {e}", ephemeral=True)
        await self.update_guild_config_async(guild.id, config)
        if created_channels_mentions:
            await interaction.followup.send(f"Automatic logging setup complete! Created/updated category {category.mention} with channels: {', '.join(created_channels_mentions)}.", ephemeral=True)
        else:
            await interaction.followup.send(f"Automatic logging setup complete! Category {category.mention} already exists and channels are configured. Role `{self.log_view_role_name}` has been created/updated with view permissions.", ephemeral=True)

    @logging_group.command(name="setup_channel", description="Sets up a specific log channel for a chosen log type.")
    @app_commands.choices(log_type=[
        app_commands.Choice(name="System Logs", value="system"),
        app_commands.Choice(name="Member Logs", value="member"),
        app_commands.Choice(name="Message Logs", value="message"),
        app_commands.Choice(name="Voice Logs", value="voice"),
        app_commands.Choice(name="Moderation Logs", value="moderation"),
        app_commands.Choice(name="Channel Logs", value="channel"),
        app_commands.Choice(name="Server Logs", value="server"),
        app_commands.Choice(name="Webhook Logs", value="webhook"),
        app_commands.Choice(name="Role Logs", value="role"),
        app_commands.Choice(name="Application Logs", value="application") 
    ])
    async def logging_setup_channel(self, interaction: Interaction, log_type: app_commands.Choice[str], channel: TextChannel):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        config = await self.get_guild_config_async(guild.id)
        current_log_type = log_type.value
        channel_to_use = channel
        config["log_channel_ids"][current_log_type] = channel_to_use.id
        try:
            webhook = await self.create_and_save_webhook_for_channel(guild, current_log_type, channel_to_use)
            if not webhook:
                await interaction.followup.send(f"Failed to create webhook for {current_log_type} in {channel_to_use.mention}. Check bot's 'Manage Webhooks' permission.", ephemeral=True)
                return
        except Exception as e:
            print(f"Failed to set up webhook for {current_log_type} in {channel_to_use.mention}: {e}")
            await interaction.followup.send(f"Error creating webhook for {current_log_type} in {channel_to_use.mention}: {e}", ephemeral=True)
            return
        await self.update_guild_config_async(guild.id, config)
        await interaction.followup.send(f"Successfully set up {log_type.name} in {channel_to_use.mention}. The bot will now use this channel for {log_type.name}.", ephemeral=True)

    @logging_group.command(name="recreate_webhooks", description="Re-creates all logging webhooks for configured channels.")
    async def logging_recreate_webhooks(self, interaction: Interaction):
        guild_id = interaction.guild.id
        config = await self.get_guild_config_async(guild_id)
        log_channel_ids = config.get("log_channel_ids", {})
        if not log_channel_ids:
            await interaction.response.send_message("No logging channels are configured. Please run `/logging_setup_auto` first.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        config["webhooks"] = {}
        recreated_count = 0
        for log_type, channel_id in log_channel_ids.items():
            channel = interaction.guild.get_channel(channel_id)
            if not channel or not isinstance(channel, TextChannel):
                print(f"Configured channel ID {channel_id} for {log_type} is not a valid text channel or does not exist.")
                continue
            existing_webhooks = await channel.webhooks()
            for webhook in existing_webhooks:
                if webhook.user == self.bot.user:
                    try:
                        await webhook.delete(reason="Recreating logging webhooks")
                    except discord.Forbidden:
                        await interaction.followup.send(f"Missing permissions to delete existing webhooks in {channel.mention}. Please grant 'Manage Webhooks'.", ephemeral=True)
                        return
                    except Exception as e:
                        print(f"Error deleting webhook {webhook.name}: {e}")
            try:
                webhook = await self.create_and_save_webhook_for_channel(interaction.guild, log_type, channel)
                if webhook:
                    recreated_count += 1
                else:
                    await interaction.followup.send(f"Failed to re-create webhook for {log_type} in {channel.mention}. Check bot's 'Manage Webhooks' permission.", ephemeral=True)
            except Exception as e:
                print(f"Error re-creating webhook for {log_type} in {channel.mention}: {e}")
                await interaction.followup.send(f"Error re-creating webhook for {log_type} in {channel.mention}: {e}", ephemeral=True)
        await self.update_guild_config_async(guild_id, config)
        await interaction.followup.send(f"Re-created {recreated_count} logging webhooks. Check specific channels for any permission issues.", ephemeral=True)

    @logging_group.command(name="toggle", description="Enable or disable logging for this server.")
    @app_commands.choices(state=[
        app_commands.Choice(name="on", value="on"),
        app_commands.Choice(name="off", value="off")
    ])
    async def toggle_logging(self, interaction: Interaction, state: app_commands.Choice[str]):
        guild_id = interaction.guild.id
        config = await self.get_guild_config_async(guild_id)
        config["logging_enabled"] = (state.value.lower() == "on")
        await self.update_guild_config_async(guild_id, config)
        await interaction.response.send_message(f"Logging for this server has been turned {state.value.lower()}.", ephemeral=True)
        embed = discord.Embed(
            title="Logging Status",
            description=f"> **Status :** {state.value.lower().capitalize()}\n> **Action By :** {interaction.user.mention}",
            color=self.logging_color
        )
        embed.set_author(name=f"{self.bot.user.name} System Logs", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        embed.set_thumbnail(url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        await self.send_embed(interaction.guild, "system", embed)

    @logging_group.command(name="status", description="Show the current logging configuration for this server.")
    async def logging_status(self, interaction: Interaction):
        guild_id = interaction.guild.id
        config = await self.get_guild_config_async(guild_id)
        logging_enabled_status = "Enabled" if config.get("logging_enabled") else "Disabled"
        category_id = config.get("log_category_id")
        category = interaction.guild.get_channel(category_id) if category_id else None
        category_mention = category.mention if category else "Not Set"
        channel_status_lines = []
        log_channel_ids = config.get("log_channel_ids", {})
        for log_type in self.log_types:
            channel_id = log_channel_ids.get(log_type)
            channel_obj = interaction.guild.get_channel(channel_id) if channel_id else None
            channel_mention = channel_obj.mention if channel_obj else "Not Set"
            channel_status_lines.append(f"- **{log_type.title()} Logs:** {channel_mention}")
        webhook_status_lines = []
        webhooks_config = config.get("webhooks", {})
        for log_type in self.log_types:
            webhook_url = webhooks_config.get(log_type)
            if webhook_url:
                webhook_status_lines.append(f"- **{log_type.title()}:** Configured")
            else:
                webhook_status_lines.append(f"- **{log_type.title()}:** Not Configured")
        description = (
            f"> **Status :** {logging_enabled_status}\n"
            f"> **Category :** {category_mention}\n\n"
            f"**__Logging Channels__**\n"
            f"{'```\n' + 'Not configured yet.\n```' if not channel_status_lines else '\n'.join(channel_status_lines)}\n\n"
            f"**__Webhook Status__**\n"
            f"{'```\n' + 'No webhooks configured yet.\n```' if not webhook_status_lines else '\n'.join(webhook_status_lines)}\n\n"
            f"- **Checked By :** {interaction.user.mention}\n"
            f"- **Time :** {get_indian_time().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        status_embed = discord.Embed(
            title="Server Logging Configuration",
            description=description,
            color=self.logging_color
        )
        status_embed.set_author(name=f"{self.bot.user.name} Logging system", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        status_embed.set_thumbnail(url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        status_embed.set_footer(text=f"{self.bot.user.name} • Logging Status", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        await interaction.response.send_message(embed=status_embed, ephemeral=True)

    @logging_group.command(name="features", description="Shows all available logging features.")
    async def logging_features(self, interaction: Interaction):
        features_list = []
        for log_type, details in self.log_channel_details.items():
            features_list.append(f"- `{details['emoji']} {log_type.replace('_', ' ').title()} Logs:` ```Tracks {log_type.replace('_', ' ').lower()} related events.```")
        
        description = (
            f"> **__Available Logging Features__**\n"
            f"> This lists all the types of events this logging system can track.\n\n"
            f"{'\n'.join(features_list)}\n\n"
            f"- **Checked By :** {interaction.user.mention}\n"
            f"- **Time :** {get_indian_time().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        features_embed = discord.Embed(
            title="Logging Features Overview",
            description=description,
            color=self.logging_color
        )
        features_embed.set_author(name=f"{self.bot.user.name} Logging system", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        features_embed.set_thumbnail(url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        features_embed.set_footer(text=f"{self.bot.user.name} • Logging Features", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)

        await interaction.response.send_message(embed=features_embed, ephemeral=True)

    @logging_group.command(name="help", description="Shows how to fully set up the logging system.")
    async def logging_help(self, interaction: Interaction):
        description = (
            f"> **__Logging Setup Guide__**\n"
            f"> This guide will help you set up and manage the server logging system.\n\n"
            f"**__Commands__**\n\n"
            f"**`/logging setup_auto`**\n"
            f"- This command automatically sets up the entire logging infrastructure. It will:\n"
            f"  - Create a new category named `✦────── 💬│Server_Logs ─────────✦` (if it doesn't exist).\n"
            f"  - Create individual text channels for different log types (e.g., `》》system_logs『💻』`, `》》member_logs『👤』`, etc.) within that category.\n"
            f"  - Set up webhooks in each log channel for efficient and reliable log delivery.\n"
            f"  - Create a role called `log_view` which has permissions to view the log channels.\n\n"
            f"- **Required Bot Permissions:** `Manage Channels`, `Manage Webhooks`, `Manage Roles` (to create/update the category, channels, webhooks, and the `log_view` role).\n\n"
            f"**`/logging setup_channel [log_type] [channel (optional)]`**\n"
            f"- This command allows you to set up a specific log channel. You can choose the `log_type` (e.g., `member`, `message`, `voice`, etc.) and optionally provide an existing `channel`.\n"
            f"  - If no channel is provided for a specific `log_type`, a new one will be created in the logging category.\n"
            f"- **Required Bot Permissions:** `Manage Channels`, `Manage Webhooks`.\n\n"
            f"**`/logging recreate_webhooks`**\n"
            f"- Use this command if your logging webhooks stop working or are deleted accidentally. It will delete existing bot-created webhooks in the log channels and create new ones.\n\n"
            f"- **Required Bot Permissions:** `Manage Webhooks`.\n\n"
            f"**`/logging toggle [on|off]`**\n"
            f"- Use this command to enable or disable the logging system for your server entirely. Choose `on` to activate logging, or `off` to pause it.\n\n"
            f"**`/logging status`**\n"
            f"- This command displays the current configuration of the logging system, including whether logging is enabled, the category used, and the status of individual log channels and their webhooks.\n\n"
            f"**`/logging features`**\n"
            f"- This command displays a list of all the different types of logging features available with this bot, such as system, member, message, voice, moderation, channel, and server logs.\n\n"
            f"**__Important: Permissions & Viewing Logs__**\n"
            f"- After running `/logging setup_auto`:\n"
            f"  1. Ensure the bot has all the necessary permissions (`Manage Channels`, `Manage Webhooks`, `Manage Roles`).\n"
            f"  2. To allow specific staff members to view the log channels, simply assign them the automatically created **`log_view`** role.\n\n"
            f"- **Time :** {get_indian_time().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        help_embed = discord.Embed(
            title="Logging Setup Guide", 
            description=description,
            color=self.logging_color
        )
        help_embed.set_author(name=f"{self.bot.user.name} Logging system", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        help_embed.set_thumbnail(url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        help_embed.set_footer(text=f"{self.bot.user.name} • Logging Help", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        await interaction.response.send_message(embed=help_embed, ephemeral=True)

    @logging_group.command(name="clear_setup", description="Clears the entire logging setup for this server.") 
    async def logging_clear_setup(self, interaction: Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        config = await self.get_guild_config_async(guild.id)
        feedback_messages = []
        config["logging_enabled"] = False

        category_id = config.get("log_category_id")
        if category_id:
            category = guild.get_channel(category_id)
            if category and isinstance(category, CategoryChannel):
                try:
                    for channel in category.channels:
                        await channel.delete(reason="Logging setup cleared by command.")
                        feedback_messages.append(f"Deleted channel: `{channel.name}`")
                    await category.delete(reason="Logging setup cleared by command.")
                    feedback_messages.append(f"Deleted logging category: `{category.name}`")
                except discord.Forbidden:
                    feedback_messages.append("I lack permissions to delete the logging category or its channels. Please grant 'Manage Channels'.")
                except Exception as e:
                    feedback_messages.append(f"Error deleting logging category: {e}")
            else:
                feedback_messages.append("Logging category not found or already deleted.")
            
            log_view_role = discord.utils.get(guild.roles, name=self.log_view_role_name)
            if log_view_role:
                try:
                    await log_view_role.delete(reason="Logging setup cleared by command.")
                    feedback_messages.append(f"Deleted role: `{self.log_view_role_name}`")
                except discord.Forbidden:
                    feedback_messages.append("I lack permissions to delete the `log_view` role. Please grant 'Manage Roles'.")
                except Exception as e:
                    feedback_messages.append(f"Error deleting `log_view` role: {e}")
            else:
                feedback_messages.append("`log_view` role not found or already deleted.")
        else:
            feedback_messages.append("No logging category was automatically set up. Clearing webhooks and database entries only.")
            for log_type, channel_id in config.get("log_channel_ids", {}).items():
                channel = guild.get_channel(channel_id)
                if channel and isinstance(channel, TextChannel):
                    try:
                        existing_webhooks = await channel.webhooks()
                        for webhook in existing_webhooks:
                            if webhook.user == self.bot.user:
                                await webhook.delete(reason=f"Clearing manual logging setup for {log_type}")
                                feedback_messages.append(f"Deleted webhook for `{log_type}` in {channel.mention}.")
                    except discord.Forbidden:
                        feedback_messages.append(f"I lack permissions to delete webhooks in {channel.mention} for {log_type}.")
                    except Exception as e:
                        feedback_messages.append(f"Error deleting webhook for {log_type} in {channel.mention}: {e}")
                else:
                    feedback_messages.append(f"Configured channel for `{log_type}` (ID: {channel_id}) not found or not a text channel. Skipping webhook deletion.")

        config["log_category_id"] = None
        config["log_channel_ids"] = {}
        config["webhooks"] = {}
        await self.update_guild_config_async(guild.id, config)
        feedback_messages.append("Logging configuration cleared from the database.")

        description_content = []
        description_content.append(f"> **__Logging Setup Clear Report__**\n")
        description_content.append(f"> This report summarizes the actions taken to clear the logging setup.\n\n")
        description_content.append(f"**__Details__**\n")
        if feedback_messages:
            for msg in feedback_messages:
                description_content.append(f"- {msg}")
        else:
            description_content.append("- No specific actions were taken or reported.")
        description_content.append(f"\n- **Cleared By :** {interaction.user.mention}")
        description_content.append(f"- **Time :** {get_indian_time().strftime('%Y-%m-%d %H:%M:%S')}")
        description = "\n".join(description_content)

        clear_embed = discord.Embed(
            title="Logging Setup Clear Report",
            description=description,
            color=self.logging_color
        )
        clear_embed.set_author(name=f"{self.bot.user.name} Logging system", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        clear_embed.set_thumbnail(url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        clear_embed.set_footer(text=f"{self.bot.user.name} • Logging Clear", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        await interaction.followup.send(embed=clear_embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: Member):
        guild = member.guild
        current_time = get_indian_time()
        user_avatar_url = member.avatar.url if member.avatar else (self.bot.user.avatar.url if self.bot.user.avatar else None)

        if member.bot:
            title = "Bot Joined"
            description = (
                f"> **Bot :** @{member.name} ({member.mention})\n"
                f"> **Account created :** {discord.utils.format_dt(member.created_at, 'R')}\n"
                f"> **Total members :** {guild.member_count}"
            )
            invite_creator_name = ""
            invite_creator_avatar = None
        else:
            title = "User Joined"
            invite_code = "N/A"
            invite_link = "N/A"
            invite_creator_name = "Unknown Inviter"
            invite_creator_avatar = self.bot.user.avatar.url if self.bot.user.avatar else None

            try:
                invites = await guild.invites()
                potential_invite = max(invites, key=lambda i: i.uses if i.uses is not None else -1, default=None)
                
                if potential_invite and potential_invite.uses and potential_invite.uses > 0:
                    invite_code = potential_invite.code
                    invite_link = potential_invite.url
                    if potential_invite.inviter:
                        invite_creator_name = potential_invite.inviter.name
                        invite_creator_avatar = potential_invite.inviter.avatar.url if potential_invite.inviter.avatar else invite_creator_avatar
            except discord.Forbidden:
                pass

            description = (
                f"> **Member :** @{member.name} ({member.mention})\n"
                f"> **Invite code :** [`{invite_code}`]({invite_link})\n" 
                f"> **Account created :** {discord.utils.format_dt(member.created_at, 'R')}\n"
                f"> **Total members :** {guild.member_count}"
            )
            
        embed = discord.Embed(
            title=title,
            description=description,
            color=11579568,
            timestamp=current_time
        )
        embed.set_footer(text=f"{invite_creator_name}", icon_url=invite_creator_avatar if invite_creator_avatar else (self.bot.user.avatar.url if self.bot.user.avatar else None))
        embed.set_thumbnail(url=user_avatar_url)
        await self.send_embed(guild, "server", embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: Member):
        guild = member.guild
        current_time = get_indian_time()
        user_avatar_url = member.avatar.url if member.avatar else (self.bot.user.avatar.url if self.bot.user.avatar else None)

        if member.bot:
            title = "Bot left"
            description_lines = [
                f"> **Bot :** @{member.name} ({member.mention})",
                f"> **Joined :** {discord.utils.format_dt(member.joined_at, 'R')}",
                f"> **Total members :** {guild.member_count}"
            ]
        else:
            title = "User left"
            description_lines = [
                f"> **Member :** @{member.name} ({member.mention})",
                f"> **Joined :** {discord.utils.format_dt(member.joined_at, 'R')}",
                f"> **Total members :** {guild.member_count}"
            ]
            roles_list = [role.mention for role in member.roles if role.name != "@everyone"]
            if roles_list:
                description_lines.append(f"> **Roles :** {', '.join(roles_list)}")

        embed = discord.Embed(
            title=title,
            description="\n".join(description_lines),
            color=13514294,
            timestamp=current_time
        )
        embed.set_thumbnail(url=user_avatar_url)
        await self.send_embed(guild, "server", embed)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return
        if message.author.bot:
            files_to_send = []
            attachment_details_for_embed = []
            if message.attachments:
                for a in message.attachments:
                    try:
                        file = await a.to_file()
                        files_to_send.append(file)
                        attachment_details_for_embed.append(f"> [{a.filename}]({a.url})")
                    except Exception as e:
                        print(f"Error converting attachment '{a.filename}' to file for logging: {e}")
                        attachment_details_for_embed.append(f"> [{a.filename}]({a.url}) (Failed to embed)")
                        
            embed_details_for_embed = []
            if message.embeds:
                for embed_obj in message.embeds:
                    embed_details_for_embed.append(f"{embed_obj.title if embed_obj.title else ''}")
                    embed_details_for_embed.append(f"{embed_obj.description if embed_obj.description else ''}")
                    if embed_obj.fields: 
                        for field in embed_obj.fields:
                            embed_details_for_embed.append(f"{field.name}\n{field.value}")
                    if embed_obj.image:
                        embed_details_for_embed.append(f"{embed_obj.image.url if embed_obj.image else ''}")
                    if embed_obj.thumbnail:
                        embed_details_for_embed.append(f"{embed_obj.thumbnail.url if embed_obj.thumbnail else ''}")
                    if embed_obj.footer: 
                        embed_details_for_embed.append(f"{embed_obj.footer.text if embed_obj.footer else ''}") 

            description = (
                f"> **Channel :** {message.channel.name} ({message.channel.mention})\n"
                f"> **Message ID :** [{message.id}]({message.jump_url})\n"
                f"> **Message author :** @{message.author.name} ({message.author.mention})\n"
                f"> **Message created : ** <t:{int(message.created_at.timestamp())}:R>"
            )
            fields = []
            if message.content:
                fields.append({
                    "name": "Message",
                    "value": message.content,
                    "inline": False
                })
            if embed_details_for_embed:
                embeds_value = "\n".join(embed_details_for_embed)
                if message.content:
                    fields.append({
                        "name": f"Embed Content",
                        "value": embeds_value,
                        "inline": False
                    })
                else:
                    fields.append({
                        "name": f"Message",
                        "value": embeds_value,
                        "inline": False
                    })
            if attachment_details_for_embed:
                attachments_value = ",\n".join(attachment_details_for_embed)
                fields.append({
                    "name": f"{len(attachment_details_for_embed)} Attachment(s)",
                    "value": attachments_value,
                    "inline": False 
                })
            embed = discord.Embed(
                title="Message Deleted",
                description=description,
                color=0xce3636,
                timestamp=get_indian_time()
            )
            for field in fields:
                embed.add_field(name=field["name"], value=field["value"], inline=field["inline"])
            await self.send_embed_files(message.guild, "message", embed, files=files_to_send)
            return 
        files_to_send = []
        attachment_details_for_embed = []
        if message.attachments:
            for a in message.attachments:
                try:
                    file = await a.to_file()
                    files_to_send.append(file)
                    attachment_details_for_embed.append(f"> [{a.filename}]({a.url})")
                except Exception as e:
                    print(f"Error converting attachment '{a.filename}' to file for logging: {e}")
                    attachment_details_for_embed.append(f"> [{a.filename}]({a.url}) (Failed to embed)")
        description = (
            f"> **Channel :** {message.channel.name} ({message.channel.mention})\n"
            f"> **Message ID :** [{message.id}]({message.jump_url})\n"
            f"> **Message author :** @{message.author.name} ({message.author.mention})\n"
            f"> **Message created : ** <t:{int(message.created_at.timestamp())}:R>"
        )
        fields = []
        if message.content:
            fields.append({
                "name": "Message",
                "value": message.content,
                "inline": False
            })
        if attachment_details_for_embed:
            attachments_value = ",\n".join(attachment_details_for_embed)
            fields.append({
                "name": f"{len(attachment_details_for_embed)} Attachment(s)",
                "value": attachments_value,
                "inline": False 
            })
        embed = discord.Embed(
            title="Message Deleted",
            description=description,
            color=0xce3636,
            timestamp=get_indian_time()
        )
        for field in fields:
            embed.add_field(name=field["name"], value=field["value"], inline=field["inline"])
        await self.send_embed_files(message.guild, "message", embed, files=files_to_send)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]):
        if not messages:
            return
        messages.sort(key=lambda m: m.created_at)
        guild = messages[0].guild
        channel = messages[0].channel
        if not guild or not isinstance(channel, TextChannel):
            return
        purged_count = len(messages)
        log_content = io.StringIO()
        log_content.write(f"Bulk Message Delete Log for Channel: #{channel.name} ({channel.id})\n")
        log_content.write(f"Guild: {guild.name} ({guild.id})\n")
        log_content.write(f"Time of Event: {get_indian_time().strftime('%Y-%m-%d %H:%M:%S %Z%z')}\n")
        log_content.write(f"Total Messages Deleted: {purged_count}\n")
        log_content.write("-" * 50 + "\n\n")
        for msg in messages:
            log_content.write(f"Message ID: {msg.id}\n")
            log_content.write(f"Author: {msg.author.display_name} ({msg.author.id}) - Bot: {msg.author.bot}\n")
            log_content.write(f"Created At: {msg.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
            log_content.write(f"Content:\n```\n{msg.content if msg.content else '[No text content]'}\n```\n")
            if msg.embeds:
                log_content.write("Embeds:\n")
                for embed in msg.embeds: 
                    color_hex = f"#{embed.color.value:06X}" if embed.color else 'N/A'
                    log_content.write(f"  Title: {embed.title if embed.title else 'N/A'}\n")
                    log_content.write(f"  Description: {embed.description if embed.description else 'N/A'}\n")
                    log_content.write(f"  URL: {embed.url if embed.url else 'N/A'}\n")
                    log_content.write(f"  Color: {color_hex}\n")
                    log_content.write(f"  Fields: {len(embed.fields)}\n")
                    for field in embed.fields:
                        log_content.write(f"    - Name: {field.name}, Value: {field.value}, Inline: {field.inline}\n")
                log_content.write("\n")
            if msg.attachments:
                log_content.write("Attachments:\n")
                for att in msg.attachments:
                    log_content.write(f"  - Filename: {att.filename}, URL: {att.url}, Size: {att.size} bytes\n")
                log_content.write("\n")
            log_content.write("-" * 30 + "\n") 
        log_file_name = f"bulk_delete_log_{channel.name}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        log_file = discord.File(io.BytesIO(log_content.getvalue().encode('utf-8')), filename=log_file_name)
        embed = discord.Embed(
            title=f"{purged_count} Messages Deleted",
            description=f"> **Channel :** {channel.name} ({channel.mention})",
            color=0xce3636,
            timestamp=get_indian_time()
        )
        embed.set_footer(text="/")
        await self.send_embed_files(guild, "message", embed, files=[log_file])

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.guild is None or before.author.bot or(before.content == after.content and before.embeds == after.embeds):
            return
        def extract_embed_details(embed: discord.Embed):
            details = []
            if embed.title:
                details.append(f"{embed.title}")
            if embed.description:
                details.append(f"{embed.description}")
            if embed.fields:
                for field in embed.fields:
                    details.append(f"{field.name}")
                    details.append(f"{field.value}")
            if embed.thumbnail and embed.thumbnail.url:
                details.append(f"{embed.thumbnail.url}")
            if embed.footer and embed.footer.text:
                details.append(f"{embed.footer.text}")
            return "\n".join(details) if details else ""
        before_content_value = ""
        if before.content:
            before_content_value += f"{before.content}"
        if before.embeds:
            for i, embed in enumerate(before.embeds):
                before_content_value += f"\n{extract_embed_details(embed)}"
        if not before.content and not before.embeds:
            before_content_value = None
        after_content_value = ""
        if after.content:
            after_content_value += f"{after.content}"
        if after.embeds:
            for i, embed in enumerate(after.embeds):
                after_content_value += f"\n{extract_embed_details(embed)}"
        if not after.content and not after.embeds:
            after_content_value = None
        description = (
                f"> **Channel :** {before.channel.name} ({before.channel.mention})\n"
                f"> **Message ID :** [{before.id}]({before.jump_url})\n"
                f"> **Message author :** @{before.author.name} ({before.author.mention})\n" 
                f"> **Message created : ** <t:{int(before.created_at.timestamp())}:R>"
        )
        embed = discord.Embed(
            title="Message Edited",
            description=description,
            color=0xffaa00,
            timestamp=get_indian_time()
        )
        if not before_content_value == None :
            embed.add_field(name="Before", value=before_content_value, inline=True)
        if not after_content_value == None :
            embed.add_field(name="After", value=after_content_value, inline=True)
        await self.send_embed(before.guild, "message", embed)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or payload.member and payload.member.bot:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        channel = guild.get_channel(payload.channel_id)
        if not channel or not isinstance(channel, TextChannel):
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            message = None
        description = (
                f"> **Channel :** {channel.name} ({channel.mention})\n"
                f"> **Message ID :** [{message.id}]({message.jump_url if message else 'https://discord.com'})\n"
                f"> **Message author :** @{message.author.name} ({message.author.mention})\n" 
                f"> **Message created : ** <t:{int(message.created_at.timestamp())}:R>\n\n"
                f"- **Reaction :** {payload.emoji}"
        )
        embed = discord.Embed(
            title="Reaction Added",
            description=description,
            color=0xff5858,
            timestamp=get_indian_time()
        )
        embed.set_footer(icon_url=payload.member.display_avatar.url,text=payload.member.name)
        await self.send_embed(guild, "message", embed)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or payload.member and payload.member.bot:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        channel = guild.get_channel(payload.channel_id)
        if not channel or not isinstance(channel, TextChannel):
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            message = None
        member = guild.get_member(payload.user_id)
        if member and member.bot:
            return
        description = (
                f"> **Channel :** {channel.name} ({channel.mention})\n"
                f"> **Message ID :** [{message.id}]({message.jump_url if message else 'https://discord.com'})\n"
                f"> **Message author :** @{message.author.name} ({message.author.mention})\n" 
                f"> **Message created : ** <t:{int(message.created_at.timestamp())}:R>\n\n"
                f"- **Reaction :** {payload.emoji}"
        )
        embed = discord.Embed(
            title="Reaction Removed",
            description=description,
            color=0xff5858,
            timestamp=get_indian_time()
        )
        embed.set_footer(icon_url=member.display_avatar.url,text=member.name)
        await self.send_embed(guild, "message", embed)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        if not channel.guild:
            return
        creator = None
        try:
            async for entry in channel.guild.audit_logs(limit=1, action=AuditLogAction.channel_create):
                if entry.target.id == channel.id and (get_indian_time() - entry.created_at).total_seconds() < 5:
                    creator = entry.user
                    break
        except discord.Forbidden:
            pass 
        category_name = channel.category.name if channel.category else "None"
        description=(
                f"> **Channel Name:** {channel.name}\n> ({channel.mention})\n"
                f"> **Channel ID :** {channel.id}\n"
                f"> **Category :** {category_name}\n"
                f"> **Position : ** {channel.position}"
            )
        embed = discord.Embed(
            title=f"{str(channel.type).capitalize()} Channel Created", 
            description=description,
            color=0xff5858 ,
            timestamp=get_indian_time()
        )
        embed.set_footer(
            text=f"{creator.name if creator else self.bot.user.name}", 
            icon_url=creator.avatar.url if creator and creator.avatar else (self.bot.user.avatar.url if self.bot.user.avatar else None) 
        )
        embed.set_thumbnail(url=creator.avatar.url if creator and creator.avatar else (self.bot.user.avatar.url if self.bot.user.avatar else None))
        await self.send_embed(channel.guild, "channel", embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        if not channel.guild:
            return
        deleter = None
        try:
            async for entry in channel.guild.audit_logs(limit=1, action=AuditLogAction.channel_delete):
                if entry.target.id == channel.id and (get_indian_time() - entry.created_at).total_seconds() < 5:
                    deleter = entry.user
                    break
        except discord.Forbidden:
            pass 
        category_name = channel.category.name if channel.category else "None"
        description=(
                f"> **Channel Name:** {channel.name}\n"
                f"> **Channel ID :** {channel.id}\n"
                f"> **Category :** {category_name}"
            )
        embed = discord.Embed(
            title=f"{str(channel.type).capitalize()} Channel Deleted", 
            description=description,
            color=0xCE3E3E,
            timestamp=get_indian_time()
        )
        embed.set_footer(
            text=f"{deleter.name if deleter else self.bot.user.name}", 
            icon_url=deleter.avatar.url if deleter and deleter.avatar else (self.bot.user.avatar.url if self.bot.user.avatar else None)
        )
        embed.set_thumbnail(url=deleter.avatar.url if deleter and deleter.avatar else (self.bot.user.avatar.url if self.bot.user.avatar else None))
        await self.send_embed(channel.guild, "channel", embed)

    def _create_channel_update_embed(self, channel, action_user, audit_log_reason, specific_description_part):
        reason_line = ""
        if audit_log_reason and audit_log_reason not in ["Missing Audit Log permissions", "Error fetching reason"]:
            reason_line = f"\n> **Reason :** {audit_log_reason}"

        description = (
            f"> **Channel :** {channel.name} ({channel.mention})\n"
            f"> **Channel ID :** {channel.id} \n"
            f"{specific_description_part}"
            f"{reason_line}"
        )

        embed = discord.Embed(
            title="Channel updated",
            description=description,
            color=11579568
        )
        embed.set_footer(
            text=f"{action_user.name}" if action_user else self.bot.user.name,
            icon_url=action_user.avatar.url if action_user and action_user.avatar else (self.bot.user.avatar.url if self.bot.user.avatar else None)
        )
        embed.timestamp = get_indian_time()
        return embed

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        if not before.guild:
            return
        action_user = None
        audit_log_reason = None 
        try:
            async for entry in before.guild.audit_logs(limit=5, action=AuditLogAction.channel_update):
                if entry.target.id == after.id and (get_indian_time() - entry.created_at).total_seconds() < 10:
                    action_user = entry.user
                    audit_log_reason = entry.reason
                    break
        except discord.Forbidden:
            action_user = None
            audit_log_reason = "Missing Audit Log permissions"
        except Exception as e:
            print(f"Error fetching audit log for channel update: {e}")
            action_user = None
            audit_log_reason = "Error fetching reason"
        embed = discord.Embed(
            title="Channel Updated",
            description=f"> **Channel :** {after.name} ({after.mention})\n> **Channel ID :** {after.id}",
            color=0x96d8a3
        )
        embeds_to_send = []
        def get_reason_line(reason):
            if reason and reason not in ["Missing Audit Log permissions", "Error fetching reason"]:
                return f"\n- **Reason :** {reason}"
            return ""
        if isinstance(before, (TextChannel, VoiceChannel)) and isinstance(after, (TextChannel, VoiceChannel)) and before.is_nsfw() != after.is_nsfw():
            after_nsfw_status = SR_CHECK if after.is_nsfw() else ERROR
            before_nsfw_status = SR_CHECK if before.is_nsfw() else ERROR
            specific_description = (
                f"> **Currently Nsfw :** {after_nsfw_status}\n"
                f"> **Previously Nsfw :** {before_nsfw_status}"
            )
            embeds_to_send.append(self._create_channel_update_embed(after, action_user, audit_log_reason, specific_description))
        type_map = {
            discord.ChannelType.text: "Text",
            discord.ChannelType.voice: "Voice",
            discord.ChannelType.category: "Category",
            discord.ChannelType.news: "Announcement",
            discord.ChannelType.stage_voice: "Stage",
            discord.ChannelType.forum: "Forum",
        }
        if before.type != after.type:
            old_type_name = type_map.get(before.type, str(before.type).replace('ChannelType.', '').capitalize())
            new_type_name = type_map.get(after.type, str(after.type).replace('ChannelType.', '').capitalize())
            specific_description = (
                f"> **Current type :** {new_type_name}\n"
                f"> **Previous type :** {old_type_name}"
            )
            embeds_to_send.append(self._create_channel_update_embed(after, action_user, audit_log_reason, specific_description))
        if isinstance(before, (TextChannel, VoiceChannel)) and isinstance(after, (TextChannel, VoiceChannel)) and before.slowmode_delay != after.slowmode_delay:
            specific_description = (
                f"> **Slowmode :** `{after.slowmode_delay}s`\n"
                f"> **Previously :** `{before.slowmode_delay}s`"
            )
            embeds_to_send.append(self._create_channel_update_embed(after, action_user, audit_log_reason, specific_description))
        if before.category != after.category:
            specific_description = (
                f"> **Current Category :** {after.category.name if after.category else 'None'}\n"
                f"> **Previous Category :** {before.category.name if before.category else 'None'}"
            )
            embeds_to_send.append(self._create_channel_update_embed(after, action_user, audit_log_reason, specific_description))
        if isinstance(before, (TextChannel, discord.ForumChannel)) and \
           isinstance(after, (TextChannel, discord.ForumChannel)) and \
           before.topic != after.topic:
            specific_description = (
                f"> **Current Topic :**``` {after.topic if after.topic else 'None'}```\n"
                f"> **Previous Topic:** ```{before.topic if before.topic else 'None'}```"
            )
            embeds_to_send.append(self._create_channel_update_embed(after, action_user, audit_log_reason, specific_description))
        if before.name != after.name:
            specific_description = (
                f"> **Previous Name :** {before.name}"
            )
            embeds_to_send.append(self._create_channel_update_embed(after, action_user, audit_log_reason, specific_description))
        if isinstance(before, (VoiceChannel, StageChannel)) and isinstance(after, (VoiceChannel, StageChannel)) and before.bitrate != after.bitrate:
            specific_description = (
                f"> **Current Bitrate :** {after.bitrate / 1000}kbps\n"
                f"> **Previous Bitrate :** {before.bitrate / 1000}kbps"
            )
            embeds_to_send.append(self._create_channel_update_embed(after, action_user, audit_log_reason, specific_description))
        if isinstance(before, (VoiceChannel, StageChannel)) and isinstance(after, (VoiceChannel, StageChannel)) and getattr(before, 'video_quality_mode', None) != getattr(after, 'video_quality_mode', None):
            old_quality = str(getattr(before, 'video_quality_mode', 'N/A')).replace('VideoQualityMode.', '')
            new_quality = str(getattr(after, 'video_quality_mode', 'N/A')).replace('VideoQualityMode.', '')
            specific_description = (
                f"> **Current Quality :** {new_quality}\n"
                f"> **Previous Quality :** {old_quality}"
            )
            embeds_to_send.append(self._create_channel_update_embed(after, action_user, audit_log_reason, specific_description))
        if isinstance(before, (VoiceChannel, StageChannel)) and isinstance(after, (VoiceChannel, StageChannel)) and before.user_limit != after.user_limit:
            specific_description = (
                f"> **Current User Limit :** {after.user_limit if after.user_limit else 'None'}\n"
                f"> **Previous User Limit :** {before.user_limit if before.user_limit else 'None'}"
            )
            embeds_to_send.append(self._create_channel_update_embed(after, action_user, audit_log_reason, specific_description))
        if isinstance(before, (VoiceChannel, StageChannel)) and isinstance(after, (VoiceChannel, StageChannel)) and before.rtc_region != after.rtc_region:
            specific_description = (
                f"> **Current Region :** {after.rtc_region if after.rtc_region else 'Automatic'}\n"
                f"> **Previous Region :** {before.rtc_region if before.rtc_region else 'Automatic'}"
            )
            embeds_to_send.append(self._create_channel_update_embed(after, action_user, audit_log_reason, specific_description))
        if before.overwrites != after.overwrites:
            permission_changes_dict = {}
            for target in set(before.overwrites.keys()) | set(after.overwrites.keys()):
                old_ow = before.overwrites.get(target)
                new_ow = after.overwrites.get(target)
                target_name = ""
                if isinstance(target, discord.Role):
                    if target.name == "@everyone":
                        target_name = f"Role : @everyone"
                    else :
                        target_name = f"Role : {target.mention}"
                elif isinstance(target, discord.Member):
                    target_name = f"Member: {target.mention}"
                else:
                    target_name = f"Unknown Target: {target.id}"
                current_target_changes = {}
                for perm_name in discord.Permissions.VALID_FLAGS:
                    old_value = getattr(old_ow, perm_name, None) if old_ow else None
                    new_value = getattr(new_ow, perm_name, None) if new_ow else None
                    if old_value != new_value:
                        old_str = "None" if old_value is None else "True" if old_value is True else "False"
                        new_str = "None" if new_value is None else "True" if new_value is True else "False"
                        current_target_changes[perm_name.replace('_', ' ').title()] = f"{old_str} -> {new_str}"
                if current_target_changes:
                    permission_changes_dict[target_name] = current_target_changes
            formatted_json_string = json.dumps(permission_changes_dict, indent=2)
            specific_description = (
                f"> **Permissions update:** \n"
                f"```json\n{formatted_json_string}\n```"
            )
            embeds_to_send.append(self._create_channel_update_embed(after, action_user, audit_log_reason, specific_description))
        for embed in embeds_to_send:
            await self.send_embed(after.guild, "channel", embed)

    async def _get_audit_log_entry_for_member_update(self, guild: discord.Guild, member: Member, time_window: int = 15):
        action_user = None
        audit_log_reason = None
        try:
            async for entry in guild.audit_logs(limit=10, action=AuditLogAction.member_update):
                if entry.target and entry.target.id == member.id and \
                   (get_indian_time() - entry.created_at).total_seconds() < time_window:
                    action_user = entry.user
                    audit_log_reason = entry.reason
                    break
        except discord.Forbidden:
            pass
        return action_user, audit_log_reason

    @commands.Cog.listener()
    async def on_member_update(self, before: Member, after: Member):
        if before.guild is None:
            return
        def get_reason_line_for_member(reason):
            if reason and reason not in ["Missing Audit Log permissions", "Error fetching reason", "No reason specified"]:
                return f"> **Reason :** {reason}"
            return ""
        audit_logs_role_update = []
        try:
            async for entry in before.guild.audit_logs(limit=20, action=AuditLogAction.member_role_update):
                if entry.target.id == after.id and (get_indian_time() - entry.created_at).total_seconds() < 60:
                    audit_logs_role_update.append(entry)
        except discord.Forbidden:
            print(f"Missing 'View Audit Log' permission in guild {before.guild.id}. Cannot fetch audit log entries for member updates.")
            audit_log_reason_global = "Missing Audit Log permissions" 
        except Exception as e:
            print(f"Error fetching audit logs for member update in guild {before.guild.id}: {e}")
            audit_log_reason_global = "Error fetching reason"
        else:
            audit_log_reason_global = None 
        def create_base_embed(title, color, user_avatar_url):
            embed = discord.Embed(
                title=title,
                color=color,
                timestamp=get_indian_time()
            )
            embed.set_thumbnail(url=user_avatar_url)
            return embed
        guild = before.guild
        current_time = get_indian_time()
        user_avatar_url = after.avatar.url if after.avatar else (self.bot.user.avatar.url if self.bot.user.avatar else None)
        action_user, audit_log_reason = await self._get_audit_log_entry_for_member_update(guild, after)
        actor_name = action_user.name if action_user else "Unknown User"
        actor_avatar_url = action_user.avatar.url if action_user and action_user.avatar else (self.bot.user.avatar.url if self.bot.user.avatar else None)
        reason_text = f"> **Reason :** {audit_log_reason}" if audit_log_reason else ""
        if before.nick != after.nick:
            embed = discord.Embed(
                title="Nickname Updated",
                description=(
                    f"> **Member :** {after.name} ({after.mention})\n"
                    f"> **Nickname :** {after.nick if after.nick else 'None'}\n"
                    f"> **Previous Nickname :** {before.nick if before.nick else 'None'}\n"
                    f"{reason_text}"
                ),
                color=0x469292,
                timestamp=current_time
            )
            embed.set_footer(text=f"{actor_name}", icon_url=actor_avatar_url)
            embed.set_thumbnail(url=user_avatar_url)
            await self.send_embed(guild, "member", embed)
        if before.roles != after.roles:
            added_roles = set(after.roles) - set(before.roles)
            removed_roles = set(before.roles) - set(after.roles)
            if added_roles or removed_roles:
                action_user = None
                action_reason = audit_log_reason_global
                for entry in audit_logs_role_update:
                    action_user = entry.user
                    action_reason = entry.reason
                    break 
                embed = create_base_embed(
                    "Role Updated",
                    0xb0b0b0, 
                    after.avatar.url if after.avatar else (self.bot.user.avatar.url if self.bot.user.avatar else None)
                )
                description_parts = [
                    f"> **Member :** {after.name} ({after.mention})"
                ]
                if removed_roles:
                    description_parts.append(f"> **Role removed :** {', '.join([role.mention for role in removed_roles])}")
                if added_roles:
                    description_parts.append(f"> **Role added :** {', '.join([role.mention for role in added_roles])}")
                reason_line = get_reason_line_for_member(action_reason)
                if reason_line:
                    description_parts.append(reason_line)
                embed.description = "\n".join(part for part in description_parts if part) 
                embed.set_footer(
                    text=f"{action_user.name}" if action_user else "Unknown User",
                    icon_url=action_user.avatar.url if action_user and action_user.avatar else (self.bot.user.avatar.url if self.bot.user.avatar else None)
                )
                await self.send_embed(after.guild, "member", embed)
        if before.timed_out_until != after.timed_out_until:
            if after.timed_out_until:
                duration = after.timed_out_until - current_time
                total_seconds = int(duration.total_seconds())
                if total_seconds < 60:
                    time_str = f"{total_seconds} seconds"
                elif total_seconds < 3600:
                    time_str = f"{total_seconds // 60} minutes"
                elif total_seconds < 86400:
                    time_str = f"{total_seconds // 3600} hours"
                else:
                    time_str = f"{total_seconds // 86400} days"
                embed = discord.Embed(
                    title="Timed out",
                    description=(
                        f"> **Member :** {after.name} ({after.mention})\n"
                        f"> **Timed out for :** {time_str}\n"
                        f"> **Timeout expire at :** {discord.utils.format_dt(after.timed_out_until, 'f')}\n"
                        f"{reason_text}"
                    ),
                    color=0xce3636,
                    timestamp=current_time
                )
                embed.set_footer(text=f"{actor_name}", icon_url=actor_avatar_url)
                embed.set_thumbnail(url=user_avatar_url)
                await self.send_embed(guild, "member", embed)
            elif before.timed_out_until and after.timed_out_until is None:
                embed = discord.Embed(
                    title="Timeout removed",
                    description=(
                        f"> **Member :** {after.name} ({after.mention})\n"
                        f"> **Removed :** {discord.utils.format_dt(current_time, 'R')}"
                    ),
                    color=0x464a92,
                    timestamp=current_time
                )
                embed.set_footer(text=f"{actor_name}", icon_url=actor_avatar_url)
                embed.set_thumbnail(url=user_avatar_url)
                await self.send_embed(guild, "member", embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: Guild, user: discord.User):
        if user.id == self.bot.user.id:
            return
        moderator = "Unknown"
        ban_reason = "No reason specified"
        try:
            async for entry in guild.audit_logs(limit=1, action=AuditLogAction.ban):
                if entry.target.id == user.id and (get_indian_time() - entry.created_at).total_seconds() < 5:
                    moderator = entry.user.mention
                    if entry.reason:
                        ban_reason = entry.reason
                    break
        except discord.Forbidden:
            moderator = "Unknown (Missing Audit Log permissions)"
            ban_reason = "No reason specified (Missing Audit Log permissions)"
        embed = discord.Embed(
            title="Member Banned",
            description=(
                f"> **User :** {user.mention}\n"
                f"> **User ID :** {user.id}\n"
                f"> **Moderator :** {moderator}\n"
                f"> **Reason :** {ban_reason}"
            ),
            color=self.logging_color
        )
        embed.set_author(name=f"{self.bot.user.name} Logging system", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        embed.set_thumbnail(url=user.avatar.url if user.avatar else (self.bot.user.avatar.url if self.bot.user.avatar else None))
        await self.send_embed(guild, "moderation", embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: Guild, user: discord.User):
        moderator = "Unknown"
        try:
            async for entry in guild.audit_logs(limit=1, action=AuditLogAction.unban):
                if entry.target.id == user.id and (get_indian_time() - entry.created_at).total_seconds() < 5:
                    moderator = entry.user.mention
                    break
        except discord.Forbidden:
            moderator = "Unknown (Missing Audit Log permissions)"
        embed = discord.Embed(
            title="Member Unbanned",
            description=(
                f"> **User :** {user.mention}\n"
                f"> **User ID :** {user.id}\n"
                f"> **Moderator :** {moderator}"
            ),
            color=self.logging_color
        )
        embed.set_author(name=f"{self.bot.user.name} Logging system", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        embed.set_thumbnail(url=user.avatar.url if user.avatar else (self.bot.user.avatar.url if self.bot.user.avatar else None))
        await self.send_embed(guild, "moderation", embed)

    async def get_audit_log_entry_for_role(self, guild: Guild, action_type: AuditLogAction, target_id: int, time_window: int = 60):
        action_user = None
        audit_log_reason = "No reason specified"
        try:
            async for entry in guild.audit_logs(limit=10, action=action_type):
                if entry.target and entry.target.id == target_id and \
                   (get_indian_time() - entry.created_at).total_seconds() < time_window:
                    action_user = entry.user
                    if entry.reason:
                        audit_log_reason = entry.reason
                    break
        except discord.Forbidden:
            audit_log_reason = "Missing Audit Log permissions"
        except Exception as e:
            print(f"Error fetching audit log for {action_type.name} on role {target_id}: {e}")
            audit_log_reason = "Error fetching reason"
        return action_user, audit_log_reason
    
    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        action_user, audit_log_reason = await self.get_audit_log_entry_for_role(
            role.guild, AuditLogAction.role_create, role.id
        )
        bot_managed_status = SR_CHECK if role.managed else ERROR
        embed = discord.Embed(
            title="Role Created",
            description=(
                f"> **Role :** {role.name} ({role.mention})\n"
                f"> **Role ID :** {role.id}\n"
                f"> **Bot Managed :** {bot_managed_status}\n"
                f"> **Reason :{'' if not audit_log_reason or audit_log_reason == 'No reason specified' else ' :'}** {audit_log_reason}"
            ),
            color=0xff5858
        )
        embed.set_footer(
            text=f"{action_user.name}" if action_user else "",
            icon_url=action_user.avatar.url if action_user and action_user.avatar else None
        )
        embed.timestamp = get_indian_time()
        await self.send_embed(role.guild, "role", embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        action_user, audit_log_reason = await self.get_audit_log_entry_for_role(
            role.guild, AuditLogAction.role_delete, role.id
        )
        embed = discord.Embed(
            title="Role Deleted",
            description=(
                f"> **Role :** {role.name}\n"
                f"> **Role ID :** {role.id}\n"
                f"> **Color :** #{role.color.value:06X}\n"
                f"> **Created :** <t:{int(role.created_at.timestamp())}:R>\n"
                f"> **Reason :{'' if not audit_log_reason or audit_log_reason == 'No reason specified' else ' :'}** {audit_log_reason}"
            ),
            color=0xce3636
        )
        embed.set_footer(
            text=f"{action_user.name}" if action_user else "",
            icon_url=action_user.avatar.url if action_user and action_user.avatar else None
        )
        embed.timestamp = get_indian_time()
        await self.send_embed(role.guild, "role", embed)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        def create_role_update_embed(title: str, role: discord.Role, action_user: discord.User, reason: str):
            embed = discord.Embed(
                title=title,
                color=0xb0b0b0,
                timestamp=get_indian_time()
            )
            embed.description = (
                f"> **Role :** {role.name} ({role.mention})\n"
                f"> **Role ID :** {role.id}\n"
            )
            if reason and reason not in ["Missing Audit Log permissions", "Error fetching reason", "No reason specified"]:
                embed.description += f"> **Reason :** {reason}\n"
            
            embed.set_footer(
                text=f"{action_user.name}" if action_user else "",
                icon_url=action_user.avatar.url if action_user and action_user.avatar else  None
            )
            return embed
        if before.name != after.name:
            action_user, audit_log_reason = await self.get_audit_log_entry_for_role(
                after.guild, AuditLogAction.role_update, after.id
            )
            embed = create_role_update_embed("Role name update", after, action_user, audit_log_reason)
            embed.description += (
                f"> **Previous Name :** {before.name}\n"
            )
            await self.send_embed(after.guild, "role", embed)
        if before.color != after.color:
            action_user, audit_log_reason = await self.get_audit_log_entry_for_role(
                after.guild, AuditLogAction.role_update, after.id
            )
            embed = create_role_update_embed("Role color Update", after, action_user, audit_log_reason)
            embed.description += (
                f"> **Previous Color :** #{before.color.value:06X}\n"
            )
            await self.send_embed(after.guild, "role", embed)
        if before.permissions != after.permissions:
            action_user, audit_log_reason = await self.get_audit_log_entry_for_role(
                after.guild, AuditLogAction.role_update, after.id
            )
            embed = create_role_update_embed("Role permission update", after, action_user, audit_log_reason)
            old_perms = set(p for p, v in before.permissions if v)
            new_perms = set(p for p, v in after.permissions if v)
            added_perms = new_perms - old_perms
            removed_perms = old_perms - new_perms
            if added_perms and removed_perms :
                value=", ".join([p.replace('_', ' ').title() for p in added_perms]) or "None"
                embed.description += (
                    f"> **Permission(s) added :** ```{value}```"
                )
                value=", ".join([p.replace('_', ' ').title() for p in removed_perms]) or "None",
                embed.description += (
                    f"**Permission(s) removed :** ```{value}```"
                )
            else :  
                if added_perms:
                    value=", ".join([p.replace('_', ' ').title() for p in added_perms]) or "None"
                    embed.description += (
                        f"> **Permission(s) added :** ```{value}```"
                    )
                if removed_perms:
                    value=", ".join([p.replace('_', ' ').title() for p in removed_perms]) or "None",
                    embed.description += (
                        f"> **Permission(s) removed :** ```{value}```"
                    )
            await self.send_embed(after.guild, "role", embed)
        if before.hoist != after.hoist:
            action_user, audit_log_reason = await self.get_audit_log_entry_for_role(
                after.guild, AuditLogAction.role_update, after.id
            )
            embed = create_role_update_embed("Role hoist update", after, action_user, audit_log_reason)
            embed.description += (
                f"> **Hoist :** {'Enabled' if after.hoist else 'Disabled'}\n"
            )
            await self.send_embed(after.guild, "role", embed)
        if before.mentionable != after.mentionable:
            action_user, audit_log_reason = await self.get_audit_log_entry_for_role(
                after.guild, AuditLogAction.role_update, after.id
            )
            embed = create_role_update_embed("Role mention update", after, action_user, audit_log_reason)
            embed.description += (
                f"> **Mentionable :** {'True' if after.mentionable else 'False'}\n"
            )
            await self.send_embed(after.guild, "role", embed)
        if before.icon != after.icon:
            action_user, audit_log_reason = await self.get_audit_log_entry_for_role(
                after.guild, AuditLogAction.role_update, after.id
            )
            embed = create_role_update_embed("Role icon update", after, action_user, audit_log_reason)
            old_icon_url = before.icon.url if before.icon else "None"
            new_icon_url = after.icon.url if after.icon else "None"
            embed.description += (
                f"> **New Icon :** {f'[Link]({new_icon_url})' if after.icon else 'None'}\n"
                f"> **Previous Icon :** {f'[Link]({old_icon_url})' if before.icon else 'None'}\n"
            )
            if after.icon:
                embed.set_thumbnail(url=after.icon.url)
            await self.send_embed(after.guild, "role", embed)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: Member, before: discord.VoiceState, after: discord.VoiceState):
        guild = member.guild
        current_time = get_indian_time()
        user_avatar_url = member.avatar.url if member.avatar else (self.bot.user.avatar.url if self.bot.user.avatar else None)
        if before.channel is None and after.channel is not None:
            embed = discord.Embed(
                title="User joined channel",
                description=(
                    f"> ** Member :** @{member.name} ({member.mention})\n"
                    f"> **Channel :** {after.channel.mention}\n"
                    f"> **Users :** {len(after.channel.members)}/{after.channel.user_limit if after.channel.user_limit else '∞'}"
                ),
                color=0xb0b0b0,
                timestamp=current_time
            )
            embed.set_thumbnail(url=user_avatar_url)
            await self.send_embed(guild, "voice", embed)
        elif before.channel is not None and after.channel is None:
            title = "User left channel"
            color = 0xce3636
            description = (
                f"> ** Member :** @{member.name} ({member.mention})\n"
                f"> **Channel :** {before.channel.mention}\n"
                f"> **Users :** {len(before.channel.members) if before.channel else 0}/{before.channel.user_limit if before.channel and before.channel.user_limit else '∞'}"
            )
            embed = discord.Embed(
                title=title,
                description=description,
                color=color,
                timestamp=current_time
            )
            embed.set_thumbnail(url=user_avatar_url)
            await self.send_embed(guild, "voice", embed)
        elif before.channel is not None and after.channel is not None and before.channel.id != after.channel.id:
            title = "User switched channel"
            color = 0x0099ff
            description = (
                f"> ** Member :** @{member.name} ({member.mention})\n"
                f"> **Channel :** {after.channel.mention}\n"
                f"> **Users :** {len(after.channel.members)}/{after.channel.user_limit if after.channel.user_limit else '∞'}\n"
                f"> **Previous Channel :** {before.channel.mention}"
            )
            embed = discord.Embed(
                title=title,
                description=description,
                color=color,
                timestamp=current_time
            )
            embed.set_thumbnail(url=user_avatar_url)
            await self.send_embed(guild, "voice", embed)
        else:
            changes = []
            if before.mute != after.mute:
                changes.append(f"Server Mute -> {'True' if after.mute else 'False'}")
            if before.deaf != after.deaf:
                changes.append(f"Server Deafen -> {'True' if after.deaf else 'False'}")
            if before.self_mute != after.self_mute:
                changes.append(f"Self Mute -> {'True' if after.self_mute else 'False'}")
            if before.self_deaf != after.self_deaf:
                changes.append(f"Self Deafen -> {'True' if after.self_deaf else 'False'}")
            if before.self_stream != after.self_stream:
                changes.append(f"Streaming -> {'True' if after.self_stream else 'False'}")
            if before.self_video != after.self_video: 
                changes.append(f"Video -> {'True' if after.self_video else 'False'}") 
            if before.suppress != after.suppress:
                changes.append(f"Suppressed -> {'True' if after.suppress else 'False'}")
            if not changes:
                return
            description = (
                f"> ** Member :** @{member.name} ({member.mention})\n"
                f"> **Channel :** {after.channel.mention}\n\n"
                f"```\n" + "\n".join(changes) + "\n```"
            )
            embed = discord.Embed(
                title="Voice state update",
                description=description,
                color=0xb0b0b0,
                timestamp=current_time
            )
            embed.set_thumbnail(url=user_avatar_url)
            await self.send_embed(guild, "voice", embed)

    @commands.Cog.listener()
    async def on_guild_update(self, before: Guild, after: Guild):
        if before.id != after.id:
            return
        guild = after
        action_user = None
        current_time_ist = get_indian_time()
        try:
            async for entry in guild.audit_logs(limit=1, action=AuditLogAction.guild_update):
                if (current_time_ist - entry.created_at).total_seconds() < 10:
                    action_user = entry.user
                break
        except discord.Forbidden:
            print(f"Missing 'View Audit Log' permission in guild {guild.id} for guild update logging.")
            return
        except Exception as e:
            print(f"Error fetching audit log for guild {guild.id}: {e}")
            action_user = self.bot.user
        footer_text = getattr(action_user, 'name', 'Unknown User') if action_user else 'Unknown User'
        footer_icon = getattr(action_user, 'display_avatar', None)
        footer_icon_url = footer_icon.url if footer_icon else None
        description_parts = [
            f"> **Guild :** {after.name}",
            f"> **Guild ID :** {after.id}"
        ]
        changes_made = False
        if before.name != after.name:
            description_parts.append(f"> **Name :** {before.name} -> {after.name}")
            changes_made = True
        if before.owner != after.owner:
            description_parts.append(f"> **Owner :** {before.owner.mention if before.owner else 'None'} -> {after.owner.mention if after.owner else 'None'}")
            changes_made = True
        if before.icon != after.icon:
            if before.icon:
                before_avatar = f"[Old_avatar_link]({before.icon.url})"
            else:
                before_avatar = "Old_avatar"
            if after.icon:
                after_avatar = f"[New_avatar_link]({after.icon.url})"
            else:
                after_avatar = "New_avatar"
            description_parts.append(f"> **Icon :** {before_avatar} -> {after_avatar}")
            changes_made = True
        if before.splash != after.splash:
            if before.splash:
                before_splash = f"[Old_splash_link]({before.splash.url})"
            else:
                before_splash = "Old_splash"
            if after.splash:
                after_splash = f"[New_splash_link]({after.splash.url})"
            else:
                after_splash = "New_splash"
            description_parts.append(f"> **Splash :** {before_splash} -> {after_splash}")
            changes_made = True
        if before.banner != after.banner:
            if before.banner:
                before_banner = f"[Old_banner_link]({before.banner.url})"
            else:
                before_banner = "Old_banner"
            if after.banner:
                after_banner = f"[New_banner_link]({after.banner.url})"
            else:
                after_banner = "New_banner"
            description_parts.append(f"> **Banner :** {before_banner} -> {after_banner}")
            changes_made = True
        if before.description != after.description:
            description_parts.append(f"> **Old Description :** ```{before.description if before.description else 'None'}```")
            description_parts.append(f"> **New Description :** ```{after.description if after.description else 'None'}```")
            changes_made = True
        if before.verification_level != after.verification_level:
            description_parts.append(f"> **Verification Level :** {before.verification_level.name} -> {after.verification_level.name}")
            changes_made = True
        if before.explicit_content_filter != after.explicit_content_filter:
            description_parts.append(f"> **Explicit Content Filter :** {before.explicit_content_filter.name} -> {after.explicit_content_filter.name}")
            changes_made = True
        if before.default_notifications != after.default_notifications:
            description_parts.append(f"> **Default Notifications :** {before.default_notifications.name} -> {after.default_notifications.name}")
            changes_made = True
        if before.mfa_level != after.mfa_level:
            description_parts.append(f"> **MFA Level :** {before.mfa_level.name} -> {after.mfa_level.name}")
            changes_made = True
        if before.premium_tier != after.premium_tier:
            description_parts.append(f"> **Boost Tier :** {before.premium_tier} -> {after.premium_tier}")
            changes_made = True
        if before.preferred_locale != after.preferred_locale:
            description_parts.append(f"> **Preferred Locale :** {before.preferred_locale} -> {after.preferred_locale}")
            changes_made = True
        if before.rules_channel != after.rules_channel:
            description_parts.append(f"> **Rules Channel :** {before.rules_channel.mention if before.rules_channel else 'None'} -> {after.rules_channel.mention if after.rules_channel else 'None'}")
            changes_made = True
        if before.public_updates_channel != after.public_updates_channel:
            description_parts.append(f"> **Public Updates Channel :** {before.public_updates_channel.mention if before.public_updates_channel else 'None'} -> {after.public_updates_channel.mention if after.public_updates_channel else 'None'}")
            changes_made = True
        if before.afk_channel != after.afk_channel:
            description_parts.append(f"> **AFK Channel :** {before.afk_channel.mention if before.afk_channel else 'None'} -> {after.afk_channel.mention if after.afk_channel else 'None'}")
            changes_made = True
        if before.afk_timeout != after.afk_timeout:
            description_parts.append(f"> **AFK Timeout :** {before.afk_timeout}s -> {after.afk_timeout}s")
            changes_made = True
        if before.system_channel != after.system_channel:
            description_parts.append(f"> **System Channel :** {before.system_channel.mention if before.system_channel else 'None'} -> {after.system_channel.mention if after.system_channel else 'None'}")
            changes_made = True
        if before.system_channel_flags != after.system_channel_flags:
            old_flags = [flag.name for flag in before.system_channel_flags.all()]
            new_flags = [flag.name for flag in after.system_channel_flags.all()]
            added_flags = set(new_flags) - set(old_flags)
            removed_flags = set(old_flags) - set(new_flags)
            if added_flags:
                description_parts.append(f"> **System Channel Flags Added :** {', '.join(added_flags)}")
            if removed_flags:
                description_parts.append(f"> **System Channel Flags Removed :** {', '.join(removed_flags)}")
            changes_made = True
        if before.features != after.features:
            old_features = set(before.features)
            new_features = set(after.features)
            added_features = new_features - old_features
            removed_features = old_features - new_features
            if added_features:
                description_parts.append(f"> **Features Added :** `{', '.join(added_features)}`")
            if removed_features:
                description_parts.append(f"> **Features Removed :** `{', '.join(removed_features)}`")
            changes_made = True
        if not changes_made:
            return
        embed = discord.Embed(
            title="Server Updated",
            description="\n".join(description_parts),
            color=self.logging_color,
            timestamp=get_indian_time()
        )
        embed.set_footer(text=footer_text, icon_url=footer_icon_url)
        await self.send_embed(after, "server", embed)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        creator = None
        current_time = get_indian_time()
        try:
            async for entry in invite.guild.audit_logs(limit=3, action=AuditLogAction.invite_create):
                if entry.target and entry.target.code == invite.code and (current_time - entry.created_at).total_seconds() < 5:
                    creator = entry.user
                    break
        except discord.Forbidden:
            pass
        expires_at_str = discord.utils.format_dt(invite.expires_at, "R") if invite.expires_at else "Never"
        max_uses_str = f"{invite.max_uses}" if invite.max_uses else "∞"
        embed = discord.Embed(
            title="Invite created",
            description=(
                f"> **Code :** `{invite.code}`\n"
                f"> **Channel :** {invite.channel.name} ({invite.channel.mention})\n"
                f"> **Expires :** {expires_at_str}\n"
                f"> **Max users :** {max_uses_str}"
            ),
            color=11579568,
            timestamp=current_time
        )
        if creator:
            embed.set_footer(text=f"{creator.name}", icon_url=creator.avatar.url if creator.avatar else None)
        await self.send_embed(invite.guild, "server", embed)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        deleter = None
        current_time = get_indian_time()
        try:
            async for entry in invite.guild.audit_logs(limit=3, action=AuditLogAction.invite_delete):
                if entry.target and entry.target.code == invite.code and (current_time - entry.created_at).total_seconds() < 5:
                    deleter = entry.user
                    break
        except discord.Forbidden:
            pass
        embed = discord.Embed(
            title="Invite deleted",
            description=(
                f"> **Code :** `{invite.code}`\n"
                f"> **Channel :** {invite.channel.name} ({invite.channel.mention})"
            ),
            color=13514294, 
            timestamp=current_time
        )
        if deleter:
            embed.set_footer(text=f"{deleter.name}", icon_url=deleter.avatar.url if deleter.avatar else None)
        await self.send_embed(invite.guild, "server", embed)

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: Union[TextChannel, VoiceChannel]):
        guild = channel.guild
        action_user = None
        audit_log_reason = None
        try:
            async for entry in guild.audit_logs(limit=5):
                if entry.action not in [AuditLogAction.webhook_create, AuditLogAction.webhook_delete, AuditLogAction.webhook_update]:
                    continue
                if (get_indian_time() - entry.created_at).total_seconds() > 10:
                    continue
                action_user = entry.user
                audit_log_reason = entry.reason
                if entry.action == AuditLogAction.webhook_create:
                    created_webhook = entry.target
                    description = (
                        f"> **Webhook :** {created_webhook.name}\n"
                        f"> **Webhook ID :** {created_webhook.id}\n"
                        f"> **Channel :** {channel.name} ({channel.mention})\n"
                        f"> **Type :** {'Incoming' if created_webhook.type == discord.WebhookType.incoming else 'Follower'}\n"
                    )
                    if audit_log_reason:
                        description += f"> **Reason:** {audit_log_reason}"
                    embed = discord.Embed(
                        title="Webhook Created",
                        description=description,
                        color=0x464a92,
                        timestamp=get_indian_time()
                    )
                    embed.set_footer(text=action_user.name, icon_url=action_user.display_avatar.url)
                    if created_webhook.avatar:
                        embed.set_thumbnail(url=created_webhook.avatar.url)
                    await self.send_embed(guild, "webhook", embed)
                    break 
                elif entry.action == AuditLogAction.webhook_delete:
                    deleted_webhook_info = entry.changes.before
                    description = (
                        f"> **Webhook:** {deleted_webhook_info.name}\n"
                        f"> **Webhook ID :** {entry.target.id}\n"
                        f"> **Channel:** {channel.name} ({channel.mention})\n"
                        f"> **Type:** {'Incoming' if getattr(deleted_webhook_info, 'type', 1) == 1 else 'Follower'}\n"
                    )
                    if audit_log_reason:
                        description += f"> **Reason:** {audit_log_reason}"
                    embed = discord.Embed(
                        title="Webhook Deleted",
                        description=description,
                        color=0xce3636,
                        timestamp=get_indian_time()
                    )
                    embed.set_footer(text=action_user.name, icon_url=action_user.display_avatar.url)
                    await self.send_embed(guild, "webhook", embed)
                    break 
                elif entry.action == AuditLogAction.webhook_delete:
                    deleted_webhook_info = entry.changes.before
                    description = (
                        f"> **Webhook:** {deleted_webhook_info.name}\n"
                        f"> **Webhook ID :** {entry.target.id}\n" 
                        f"> **Channel:** {channel.name} ({channel.mention})\n"
                        f"> **Type:** {'Incoming' if getattr(deleted_webhook_info, 'type', 1) == 1 else 'Follower'}\n"
                    )
                    if audit_log_reason:
                        description += f"> **Reason:** {audit_log_reason}"
                    embed = discord.Embed(
                        title="Webhook Deleted",
                        description=description,
                        color=0xce3636, 
                        timestamp=get_indian_time()
                    )
                    embed.set_footer(text=action_user.name, icon_url=action_user.display_avatar.url)
                    await self.send_embed(guild, "webhook", embed)
                    break 
                elif entry.action == AuditLogAction.webhook_update:
                    updated_webhook = entry.target
                    embeds_to_send = []
                    if hasattr(entry.changes.before, 'name') and entry.changes.before.name != entry.changes.after.name:
                        embed = discord.Embed(
                            title="Webhook Name Updated",
                            description=(
                                f"> **Webhook:** {updated_webhook.name} ({updated_webhook.id})\n"
                                f"> **Channel:** {channel.name} ({channel.mention})\n"
                                f"> **Previous Name:** {entry.changes.before.name}"
                            ),
                            color=0xb0b0b0, 
                            timestamp=get_indian_time()
                        )
                        embed.set_footer(text=action_user.name, icon_url=action_user.display_avatar.url)
                        embeds_to_send.append(embed)
                    if hasattr(entry.changes.before, 'channel') and entry.changes.before.channel != entry.changes.after.channel:
                        previous_channel = guild.get_channel(entry.changes.before.channel.id) if entry.changes.before.channel else None
                        
                        embed = discord.Embed(
                            title="Webhook Channel Updated",
                            description=(
                                f"> **Webhook:** {updated_webhook.name} ({updated_webhook.id})\n"
                                f"> **New Channel:** {channel.name} ({channel.mention})\n"
                                f"> **Previous Channel:** {previous_channel.name if previous_channel else 'Unknown'}"
                            ),
                            color=0xb0b0b0, 
                            timestamp=get_indian_time()
                        )
                        embed.set_footer(text=action_user.name, icon_url=action_user.display_avatar.url)
                        embeds_to_send.append(embed)
                    if hasattr(entry.changes.before, 'avatar') and entry.changes.before.avatar != entry.changes.after.avatar:
                        embed = discord.Embed(
                            title="Webhook Avatar Updated",
                            description=(
                                f"> **Webhook:** {updated_webhook.name} ({updated_webhook.id})\n"
                                f"> **Channel:** {channel.name} ({channel.mention})\n"
                                f"> **Previous Avatar:** {'Available' if entry.changes.before.avatar else 'Not set'}"
                            ),
                            color=0xb0b0b0,
                            timestamp=get_indian_time()
                        )
                        embed.set_footer(text=action_user.name, icon_url=action_user.display_avatar.url)
                        if updated_webhook.avatar:
                            embed.set_thumbnail(url=updated_webhook.avatar.url)
                        embeds_to_send.append(embed)
                    if embeds_to_send:
                        for embed in embeds_to_send:
                            await self.send_embed(guild, "webhook", embed)
                        break 
        except discord.Forbidden:
            print(f"Missing 'View Audit Log' permission in guild {guild.id} for webhook logging.")
        except Exception as e:
            print(f"Error in on_webhooks_update for guild {guild.id}: {e}")

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry):
        guild = entry.guild
        if not guild:
            return
        relevant_actions = [
            AuditLogAction.integration_create,
            AuditLogAction.integration_delete,
            AuditLogAction.bot_add,
        ]
        if entry.action not in relevant_actions:
            return
        if (get_indian_time() - entry.created_at).total_seconds() > 10:
            return
        action_user = entry.user
        audit_log_reason = entry.reason
        if entry.action == AuditLogAction.bot_add:
            application_user = entry.target
            application_name = getattr(application_user, 'name', "Unknown Application")
            application_id = application_user.id
            application_mention = application_user.mention
            application_avatar_url = getattr(application_user, 'display_avatar', None)
            if application_avatar_url:
                application_avatar_url = application_avatar_url.url
            description = (
                f"> ** Application :** {application_name} ({application_mention})\n"
                f"> **Application ID :** {application_id}"
            )
            if audit_log_reason:
                description += f"\n> **Reason:** {audit_log_reason}"

            embed = discord.Embed(
                title="Application Added",
                description=description,
                color=0x464a92,
                timestamp=get_indian_time()
            )
            embed.set_footer(text=action_user.name, icon_url=action_user.display_avatar.url)
            if application_avatar_url:
                embed.set_thumbnail(url=application_avatar_url)
            await self.send_embed(guild, "application", embed)
        elif entry.action == AuditLogAction.integration_delete:
            deleted_application_info = entry.changes.before
            description = (
                f"> ** Application :** {getattr(deleted_application_info, 'name', 'Unknown Application')}\n"
                f"> **Application ID :** {entry.target.id}"
            )
            if audit_log_reason:
                description += f"\n> **Reason:** {audit_log_reason}"
            embed = discord.Embed(
                title="Application removed",
                description=description,
                color=0xce3636,
                timestamp=get_indian_time()
            )
            embed.set_footer(text=action_user.name, icon_url=action_user.display_avatar.url)
            await self.send_embed(guild, "application", embed)

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild: discord.Guild, before: list[discord.Emoji], after: list[discord.Emoji]):
        current_time_ist = get_indian_time()
        try:
            if len(before) < len(after):
                new_emojis = [emoji for emoji in after if emoji not in before]
                for emoji in new_emojis:
                    action_user = None
                    audit_log_reason = None
                    async for entry in guild.audit_logs(limit=1, action=AuditLogAction.emoji_create):
                        if (current_time_ist - entry.created_at).total_seconds() < 10 and entry.target.id == emoji.id:
                            action_user = entry.user
                            audit_log_reason = entry.reason
                            break
                    if not action_user:
                        action_user = self.bot.user
                        audit_log_reason = "Not found in recent audit logs"
                    description = (
                        f"> **Name :** {emoji.name}\n"
                        f"> **Emoji ID :** {emoji.id}([emoji_url.png/gif]({emoji.url}))\n"
                        f"> **Animated :** `{emoji.animated}`\n"
                        f"> **Emoji :** {emoji}"
                    )
                    if audit_log_reason:
                        description += f"\n> **Reason:** {audit_log_reason}"
                    embed = discord.Embed(
                        title="Emoji created",
                        description=description,
                        color=0xb0b0b0,
                        timestamp=current_time_ist
                    )
                    embed.set_footer(text=action_user.name, icon_url=action_user.display_avatar.url)
                    await self.send_embed(guild, "server", embed)
            elif len(before) > len(after):
                deleted_emojis = [emoji for emoji in before if emoji not in after]
                for emoji in deleted_emojis:
                    action_user = None
                    audit_log_reason = None
                    creation_timestamp_display = "N/A"
                    async for entry in guild.audit_logs(limit=1, action=AuditLogAction.emoji_delete):
                        if (current_time_ist - entry.created_at).total_seconds() < 10 and getattr(entry.target, 'id', None) == emoji.id:
                            action_user = entry.user
                            audit_log_reason = entry.reason
                            if hasattr(emoji, 'created_at') and emoji.created_at:
                                creation_timestamp_display = f"<t:{int(emoji.created_at.timestamp())}:R>"
                            else:
                                creation_timestamp_display = "Unknown"
                            break
                    if not action_user:
                        action_user = self.bot.user
                        audit_log_reason = "Not found in recent audit logs"
                        creation_timestamp_display = "Unknown"
                    description = (
                        f"> **Name :** {emoji.name}\n"
                        f"> **Emoji ID :** {emoji.id}([emoji_url.png/gif]({emoji.url}))\n"
                        f"> **Animated :** `{emoji.animated}`\n"
                        f"> **Created :** {creation_timestamp_display}"
                    )
                    if audit_log_reason:
                        description += f"\n> **Reason:** {audit_log_reason}"
                    embed = discord.Embed(
                        title="Emoji deleted",
                        description=description,
                        color=0xce3636,
                        timestamp=current_time_ist
                    )
                    embed.set_footer(text=action_user.name, icon_url=action_user.display_avatar.url)
                    emoji_file = None
                    if emoji.url:
                        try:
                            async with aiohttp.ClientSession() as session:
                                async with session.get(emoji.url) as resp:
                                    if resp.status == 200:
                                        image_data = io.BytesIO(await resp.read())
                                        file_extension = 'gif' if emoji.animated else 'png'
                                        emoji_file = discord.File(image_data, filename=f"emoji_{emoji.id}.{file_extension}")
                        except Exception as e:
                            print(f"Error downloading emoji {emoji.id} for attachment: {e}")
                    await self.send_embed_files(guild, "server", embed, files=[emoji_file])
            else:
                for old_emoji, new_emoji in zip(before, after):
                    if old_emoji.name != new_emoji.name or \
                       old_emoji.animated != new_emoji.animated:
                        action_user = None
                        audit_log_reason = None
                        previous_name = old_emoji.name
                        async for entry in guild.audit_logs(limit=1, action=AuditLogAction.emoji_update):
                            if (current_time_ist - entry.created_at).total_seconds() < 10 and entry.target.id == new_emoji.id:
                                action_user = entry.user
                                audit_log_reason = entry.reason
                                break
                        if not action_user:
                            action_user = self.bot.user
                            audit_log_reason = "Not found in recent audit logs"
                        description = (
                            f"> **Name :** {new_emoji.name}\n"
                            f"> **Emoji ID :** {new_emoji.id}([emoji_url.png/gif]({new_emoji.url}))\n"
                            f"> **Animated :** `{new_emoji.animated}`\n"
                            f"> **Previous Name :** {previous_name}\n"
                            f"> **Emoji :** {new_emoji}"
                        )
                        if audit_log_reason:
                            description += f"\n> **Reason:** {audit_log_reason}"
                        embed = discord.Embed(
                            title="Emoji Updated",
                            description=description,
                            color=0x464a92,
                            timestamp=current_time_ist
                        ) 
                        embed.set_footer(text=action_user.name, icon_url=action_user.display_avatar.url)
                        await self.send_embed(guild, "server", embed)
        except discord.Forbidden:
            print(f"Missing 'View Audit Log' permission in guild {guild.id} for emoji logging.")
        except Exception as e:
            print(f"Error in on_guild_emojis_update for guild {guild.id}: {e}")

    @commands.Cog.listener()
    async def on_guild_stickers_update(self, guild: discord.Guild, before: list[discord.Sticker], after: list[discord.Sticker]):
        current_time_ist = get_indian_time()
        try:
            if len(before) < len(after):
                new_stickers = [sticker for sticker in after if sticker not in before]
                for sticker in new_stickers:
                    action_user = None
                    audit_log_reason = None
                    async for entry in guild.audit_logs(limit=1, action=AuditLogAction.sticker_create):
                        if (current_time_ist - entry.created_at).total_seconds() < 10 and entry.target.id == sticker.id:
                            action_user = entry.user
                            audit_log_reason = entry.reason
                            break
                    if not action_user:
                        action_user = self.bot.user
                        audit_log_reason = "Not found in recent audit logs"
                    sticker_extension = 'gif' if sticker.format.name == 'APNG' else 'png' if sticker.format.name == 'PNG' else 'webp'
                    sticker_url_formatted = f"[sticker_url.{sticker_extension}]({sticker.url})" if sticker.url else ""
                    description = (
                        f"> **Name :** {sticker.name}\n"
                        f"> **Sticker ID :** {sticker.id} ({sticker_url_formatted})\n"
                        f"> **Sticker Url :**{sticker_url_formatted}"
                    )
                    if audit_log_reason:
                        description += f"\n> **Reason:** {audit_log_reason}"
                    embed = discord.Embed(
                        title="Sticker created",
                        description=description,
                        color=0xb0b0b0,
                        timestamp=current_time_ist
                    )
                    embed.set_footer(text=action_user.name, icon_url=action_user.display_avatar.url)
                    await self.send_embed(guild, "server", embed)
            elif len(before) > len(after):
                deleted_stickers = [sticker for sticker in before if sticker not in after]
                for sticker in deleted_stickers:
                    action_user = None
                    audit_log_reason = None
                    creation_timestamp_display = "N/A"
                    async for entry in guild.audit_logs(limit=1, action=AuditLogAction.sticker_delete):
                        if (current_time_ist - entry.created_at).total_seconds() < 10 and getattr(entry.target, 'id', None) == sticker.id:
                            action_user = entry.user
                            audit_log_reason = entry.reason
                            if hasattr(sticker, 'created_at') and sticker.created_at:
                                creation_timestamp_display = f"<t:{int(sticker.created_at.timestamp())}:R>"
                            else:
                                creation_timestamp_display = "Unknown"
                            break
                    if not action_user:
                        action_user = self.bot.user
                        audit_log_reason = "Not found in recent audit logs"
                        creation_timestamp_display = "Unknown"
                    sticker_extension = 'gif' if sticker.format.name == 'APNG' else 'png' if sticker.format.name == 'PNG' else 'webp'
                    sticker_url_formatted = f"([sticker_url.{sticker_extension}]({sticker.url}))" if sticker.url else ""
                    description = (
                        f"> **Name :** {sticker.name}\n"
                        f"> **Sticker ID :** {sticker.id} {sticker_url_formatted}\n"
                        f"> **Created :** {creation_timestamp_display}"
                    )
                    if audit_log_reason:
                        description += f"\n> **Reason:** {audit_log_reason}"
                    embed = discord.Embed(
                        title="Sticker deleted",
                        description=description,
                        color=0xce3636,
                        timestamp=current_time_ist
                    )
                    embed.set_footer(text=action_user.name, icon_url=action_user.display_avatar.url)
                    sticker_file = None
                    if sticker.url:
                        try:
                            async with aiohttp.ClientSession() as session:
                                async with session.get(sticker.url) as resp:
                                    if resp.status == 200:
                                        image_data = io.BytesIO(await resp.read())
                                        sticker_file = discord.File(image_data, filename=f"sticker_{sticker.id}.{sticker_extension}")
                        except Exception as e:
                            print(f"Error downloading sticker {sticker.id} for attachment: {e}")
                    await self.send_embed_files(guild, "server", embed, files=[sticker_file] if sticker_file else [])
            else:
                for old_sticker, new_sticker in zip(before, after):
                    if old_sticker.id == new_sticker.id:
                        action_user = None
                        audit_log_reason = None
                        async for entry in guild.audit_logs(limit=1, action=AuditLogAction.sticker_update):
                            if (current_time_ist - entry.created_at).total_seconds() < 10 and entry.target.id == new_sticker.id:
                                action_user = entry.user
                                audit_log_reason = entry.reason
                                break
                        if not action_user:
                            action_user = self.bot.user
                            audit_log_reason = "Not found in recent audit logs"
                        sticker_extension = 'gif' if new_sticker.format.name == 'APNG' else 'png' if new_sticker.format.name == 'PNG' else 'webp'
                        sticker_url_formatted = f"([sticker_url.{sticker_extension}]({new_sticker.url}))" if new_sticker.url else ""
                        if old_sticker.name != new_sticker.name:
                            description = (
                                f"> **Name :** {new_sticker.name}\n"
                                f"> **Sticker ID :** {new_sticker.id} {sticker_url_formatted}\n"
                                f"> **Previous Name :** {old_sticker.name}"
                            )
                            if audit_log_reason:
                                description += f"\n> **Reason:** {audit_log_reason}"
                            embed = discord.Embed(
                                title="Sticker Updated",
                                description=description,
                                color=0x464a92,
                                timestamp=current_time_ist
                            )
                            embed.set_footer(text=action_user.name, icon_url=action_user.display_avatar.url)
                            await self.send_embed(guild, "server", embed)
        except discord.Forbidden:
            print(f"Missing 'View Audit Log' permission in guild {guild.id} for sticker logging.")
        except Exception as e:
            print(f"Error in on_guild_stickers_update for guild {guild.id}: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(LoggingCog(bot)) 
