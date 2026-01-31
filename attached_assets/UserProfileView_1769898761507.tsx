import { useState } from "react";
import { Avatar, AvatarImage, AvatarFallback } from "../ui/avatar";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { Camera, MapPin, Calendar, Feather, Heart, MessageCircle, Share2, Pin, Edit, ArrowLeft, Home, Users, Globe, Scroll, MapPin as WorldIcon, MessageSquare, Settings } from "lucide-react";
import { PostCard } from "../Feed/PostCard";
import { Tabs, TabsList, TabsTrigger } from "../ui/tabs";

interface UserProfileViewProps {
  onNavigate?: (view: string) => void;
}

export function UserProfileView({ onNavigate }: UserProfileViewProps) {
  const [activeTab, setActiveTab] = useState("timeline");

  // Mock user data
  const user = {
    name: "Luna Nightshade",
    username: "lunawrites",
    handle: "@lunawrites",
    avatar: "https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=400&h=400&fit=crop",
    coverImage: "https://images.unsplash.com/photo-1623489956130-64c5f8e84590?w=1200&h=400&fit=crop",
    bio: "Professional storyteller weaving tales of magic, mystery, and moonlit adventures. Lover of dark academia aesthetics and character-driven narratives.",
    writingFocus: ["Fantasy", "Dark Academia", "Romance", "Mystery"],
    location: "Mystic Isles",
    joinedDate: "Joined March 2024",
    stats: {
      posts: 342,
      characters: 12,
      realms: 8,
      followers: 1847
    }
  };

  // User timeline posts - only user-centric activity
  const timelinePosts = [
    {
      type: 'pinned' as const,
      author: {
        name: user.name,
        username: user.username,
        avatar: user.avatar,
      },
      content: `✨ Welcome to my creative space! ✨

I'm Luna, a passionate roleplay writer specializing in intricate character development and atmospheric storytelling. I love exploring the darker corners of fantasy worlds while maintaining emotional depth and authenticity.

Currently working on: The Chronicles of the Shadowmere lineage
Open to: Long-term collaborative storylines, especially those involving magical academies or forbidden romance

Feel free to reach out if you'd like to create something together!`,
      timestamp: "Pinned Post",
      likes: 234,
      comments: 67,
      shares: 45,
      tags: ["introduction", "about"],
      isPinned: true
    },
    {
      type: 'roleplay' as const,
      author: {
        name: user.name,
        username: user.username,
        avatar: user.avatar,
        characterName: "Lady Morgana Shadowmere"
      },
      content: `*The candlelight flickered across ancient tomes as she traced her fingers along the weathered spines*

"These texts speak of a power long forgotten," Morgana whispered, her emerald eyes gleaming with arcane knowledge. "A convergence of realms that occurs only once in a millennium. And it begins... tonight."

*She turned to face her companions, robes swirling like midnight mist*`,
      timestamp: "2h ago",
      likes: 127,
      comments: 34,
      shares: 12,
      tags: ["fantasy", "magic", "darkacademia"],
      realm: "Mystic Isles"
    },
    {
      type: 'character-update' as const,
      author: {
        name: user.name,
        username: user.username,
        avatar: user.avatar,
        characterName: "Lady Morgana Shadowmere"
      },
      content: `Character Development Update ✨

After years of study in the Obsidian Tower, Morgana has mastered shadow manipulation. She can now step between dimensions, though each crossing leaves her more connected to the void. Her eyes now shimmer with an otherworldly darkness - beautiful, yet unsettling.

This power comes with a price: the more she uses it, the harder it becomes to feel warmth, both literal and emotional. A tragic irony for someone who still yearns for human connection.`,
      timestamp: "1d ago",
      likes: 189,
      comments: 52,
      shares: 28,
      tags: ["characterdevelopment", "shadowmere", "magic"],
      realm: "Mystic Isles"
    },
    {
      type: 'image-moodboard' as const,
      author: {
        name: user.name,
        username: user.username,
        avatar: user.avatar
      },
      content: `New aesthetic inspiration for my upcoming character arc 🌙

Exploring themes of forbidden knowledge, ancient libraries, and the cost of pursuing truth at all costs. Morgana's journey into the darker aspects of magic continues...`,
      timestamp: "3d ago",
      likes: 156,
      comments: 41,
      shares: 67,
      tags: ["moodboard", "darkacademia", "aesthetic"],
      image: "https://images.unsplash.com/photo-1507842217343-583bb7270b66?w=800&h=400&fit=crop"
    },
    {
      type: 'profile-update' as const,
      author: {
        name: user.name,
        username: user.username,
        avatar: user.avatar
      },
      content: `📝 Writing Update

Just hit 50,000 words in the Shadowmere Chronicles! This journey has been incredible - exploring Morgana's descent into shadow magic while maintaining her core humanity has been both challenging and deeply rewarding.

Thank you to everyone who's been following along and contributing to this story. Your characters have made this world come alive! 💜`,
      timestamp: "5d ago",
      likes: 298,
      comments: 78,
      shares: 34,
      tags: ["milestone", "writing", "gratitude"]
    },
    {
      type: 'roleplay' as const,
      author: {
        name: user.name,
        username: user.username,
        avatar: user.avatar,
        characterName: "Lady Morgana Shadowmere"
      },
      content: `*Standing at the precipice of the Obsidian Tower, wind whipping her dark robes around her like living shadows*

"They say that power corrupts," she murmured to the night sky, stars reflected in her darkened eyes. "But what if corruption is simply... transformation? What if the darkness I embrace is not evil, but truth?"

*She extended her hand, shadows coalescing into tangible forms - memories, fears, possibilities*

"I have seen what lies beyond the veil. And I cannot unsee it."`,
      timestamp: "1w ago",
      likes: 234,
      comments: 89,
      shares: 45,
      tags: ["fantasy", "introspection", "character"],
      realm: "Mystic Isles"
    }
  ];

  const navItems = [
    { id: 'feed', label: 'Feed', icon: Home },
    { id: 'characters', label: 'Characters', icon: Users },
    { id: 'realms', label: 'Realms', icon: Globe },
    { id: 'scenes', label: 'Scenes', icon: Scroll },
    { id: 'worldbuilding', label: 'Worldbuilding', icon: WorldIcon },
    { id: 'messages', label: 'Messages', icon: MessageSquare },
    { id: 'settings', label: 'Settings', icon: Settings },
  ];

  return (
    <div className="min-h-screen">
      {/* Minimalist icon-only navigation bar */}
      <div className="fixed top-0 left-0 right-0 z-50 glass border-b border-white/10">
        <div className="max-w-6xl mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full gradient-primary flex items-center justify-center">
                <Feather className="w-4 h-4 text-white" />
              </div>
              <span className="text-white">OwlQuill</span>
            </div>
            
            {/* Icon-only navigation */}
            <nav className="flex items-center gap-2">
              {navItems.map((item) => {
                const Icon = item.icon;
                return (
                  <Button
                    key={item.id}
                    variant="ghost"
                    size="icon"
                    className="text-white/70 hover:text-white hover:bg-white/10"
                    onClick={() => onNavigate?.(item.id)}
                    title={item.label}
                  >
                    <Icon className="w-5 h-5" />
                  </Button>
                );
              })}
            </nav>
          </div>

          {/* User menu (current user) */}
          <div className="flex items-center gap-3">
            <Avatar className="w-9 h-9 ring-2 ring-[#1B4FFF]/50 cursor-pointer">
              <AvatarImage src="https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=200&h=200&fit=crop" />
              <AvatarFallback>AS</AvatarFallback>
            </Avatar>
          </div>
        </div>
      </div>

      {/* Profile Content */}
      <div className="pt-16">
        {/* Cover Image */}
        <div className="relative h-96 w-full overflow-hidden bg-gradient-to-br from-[#1B4FFF]/20 to-[#E66DD6]/20">
          <img 
            src={user.coverImage} 
            alt="Cover" 
            className="w-full h-full object-cover"
          />
          <div className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-[#0A0A0D]/80" />
          
          {/* Edit Cover Button */}
          <Button 
            variant="outline" 
            size="sm"
            className="absolute bottom-4 right-4 glass-strong border-white/30 text-white hover:bg-white/20"
          >
            <Camera className="w-4 h-4 mr-2" />
            Edit Cover
          </Button>
        </div>

        {/* Profile Header */}
        <div className="max-w-4xl mx-auto px-6">
          <div className="relative -mt-24 mb-6">
            {/* Avatar - right aligned */}
            <div className="flex justify-end mb-6">
              <div className="relative">
                <Avatar className="w-44 h-44 ring-4 ring-[#0A0A0D] shadow-2xl">
                  <AvatarImage src={user.avatar} />
                  <AvatarFallback className="bg-gradient-primary text-white">LN</AvatarFallback>
                </Avatar>
                <Button 
                  size="icon"
                  className="absolute bottom-2 right-2 w-11 h-11 rounded-full bg-[#1B4FFF] hover:bg-[#1B4FFF]/90 shadow-lg"
                >
                  <Camera className="w-5 h-5 text-white" />
                </Button>
              </div>
            </div>

            {/* User Info */}
            <div className="glass-strong rounded-2xl p-8">
              <div className="flex items-start justify-between mb-6">
                <div className="flex-1">
                  <h1 className="text-white mb-2 font-display">{user.name}</h1>
                  <p className="text-white/60 mb-4">{user.handle}</p>
                  
                  <p className="text-white/90 mb-5 max-w-2xl leading-relaxed">{user.bio}</p>
                  
                  {/* Writing Focus Tags */}
                  <div className="flex flex-wrap gap-2 mb-5">
                    {user.writingFocus.map((focus, idx) => (
                      <Badge 
                        key={idx}
                        className="bg-[#1B4FFF]/20 text-[#3B82F6] border border-[#1B4FFF]/30 hover:bg-[#1B4FFF]/30"
                      >
                        <Feather className="w-3 h-3 mr-1" />
                        {focus}
                      </Badge>
                    ))}
                  </div>

                  {/* Meta Info */}
                  <div className="flex items-center gap-6 text-sm text-white/60">
                    <div className="flex items-center gap-2">
                      <MapPin className="w-4 h-4" />
                      <span>{user.location}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Calendar className="w-4 h-4" />
                      <span>{user.joinedDate}</span>
                    </div>
                  </div>
                </div>

                {/* Action Buttons */}
                <div className="flex gap-3">
                  <Button 
                    variant="outline" 
                    className="border-white/20 text-white hover:bg-white/10"
                  >
                    <MessageCircle className="w-4 h-4 mr-2" />
                    Message
                  </Button>
                  <Button className="gradient-primary text-white glow-hover">
                    <Heart className="w-4 h-4 mr-2" />
                    Follow
                  </Button>
                  <Button 
                    variant="outline"
                    size="icon"
                    className="border-white/20 text-white hover:bg-white/10"
                  >
                    <Share2 className="w-4 h-4" />
                  </Button>
                </div>
              </div>

              {/* Stats */}
              <div className="flex items-center gap-8 pt-6 border-t border-white/10">
                <button className="text-center hover:opacity-80 transition-opacity">
                  <div className="text-white mb-1">{user.stats.posts}</div>
                  <div className="text-white/60 text-sm">Posts</div>
                </button>
                <button className="text-center hover:opacity-80 transition-opacity">
                  <div className="text-white mb-1">{user.stats.characters}</div>
                  <div className="text-white/60 text-sm">Characters</div>
                </button>
                <button className="text-center hover:opacity-80 transition-opacity">
                  <div className="text-white mb-1">{user.stats.realms}</div>
                  <div className="text-white/60 text-sm">Realms</div>
                </button>
                <button className="text-center hover:opacity-80 transition-opacity">
                  <div className="text-white mb-1">{user.stats.followers.toLocaleString()}</div>
                  <div className="text-white/60 text-sm">Followers</div>
                </button>
              </div>
            </div>

            {/* Tabs Navigation */}
            <div className="mt-6 glass rounded-xl p-1">
              <Tabs value={activeTab} onValueChange={setActiveTab}>
                <TabsList className="w-full bg-transparent border-0 gap-1">
                  <TabsTrigger 
                    value="timeline" 
                    className="flex-1 data-[state=active]:bg-[#1B4FFF] data-[state=active]:text-white text-white/60 rounded-lg"
                  >
                    Timeline
                  </TabsTrigger>
                  <TabsTrigger 
                    value="stories" 
                    className="flex-1 data-[state=active]:bg-[#1B4FFF] data-[state=active]:text-white text-white/60 rounded-lg"
                  >
                    Stories
                  </TabsTrigger>
                  <TabsTrigger 
                    value="media" 
                    className="flex-1 data-[state=active]:bg-[#1B4FFF] data-[state=active]:text-white text-white/60 rounded-lg"
                  >
                    Media
                  </TabsTrigger>
                  <TabsTrigger 
                    value="mentions" 
                    className="flex-1 data-[state=active]:bg-[#1B4FFF] data-[state=active]:text-white text-white/60 rounded-lg"
                  >
                    Mentions
                  </TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
          </div>

          {/* Tab Content */}
          <div className="pb-12">
            {activeTab === "timeline" && (
              <div className="space-y-6">
                {timelinePosts.map((post, idx) => (
                  <div key={idx} className="relative">
                    {post.isPinned && (
                      <div className="absolute -top-2 left-4 z-20">
                        <Badge className="bg-[#F5C04E] text-[#0A0A0D] border-none shadow-lg">
                          <Pin className="w-3 h-3 mr-1" />
                          Pinned
                        </Badge>
                      </div>
                    )}
                    <PostCard {...post} />
                  </div>
                ))}
              </div>
            )}

            {activeTab === "stories" && (
              <div className="glass-strong rounded-2xl p-12 text-center">
                <Scroll className="w-12 h-12 text-white/40 mx-auto mb-4" />
                <h3 className="text-white mb-2">No Stories Yet</h3>
                <p className="text-white/60">Your long-form stories and campaigns will appear here</p>
              </div>
            )}

            {activeTab === "media" && (
              <div className="glass-strong rounded-2xl p-12 text-center">
                <Camera className="w-12 h-12 text-white/40 mx-auto mb-4" />
                <h3 className="text-white mb-2">No Media Yet</h3>
                <p className="text-white/60">Images and moodboards you've shared will appear here</p>
              </div>
            )}

            {activeTab === "mentions" && (
              <div className="glass-strong rounded-2xl p-12 text-center">
                <MessageCircle className="w-12 h-12 text-white/40 mx-auto mb-4" />
                <h3 className="text-white mb-2">No Mentions Yet</h3>
                <p className="text-white/60">Posts where you've been mentioned will appear here</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
