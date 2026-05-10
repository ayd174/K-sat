import os
import subprocess
import PIL.Image
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips

def generate_audio(text, output_file):
    print(f"Generating audio for: {output_file}")
    # Run edge-tts to generate speech
    subprocess.run([
        "python", "-m", "edge_tts", 
        "--text", text, 
        "--voice", "tr-TR-AhmetNeural",  # High quality Turkish male voice
        "--write-media", output_file
    ], check=True)

def create_video():
    texts = [
        "Siparişlerin, rotaların ve takibin birbirine karıştığı o eski günleri unutun. Lojistikte kontrolü ele almanın ve büyümenin en akıllı yoluyla tanışın: AYKA Transport Platformu.",
        "Sisteme entegre Yapay Zeka Destekli Asistanınız, siz uyurken bile gece-gündüz telefon üzerinden sipariş alır, sesi metne dönüştürür. Mükemmel bir müşteri deneyimine otomatik geçiş...",
        "Sipariş alındığı an, sahadaki ekibinizin cebinde! AYKA Driver App sayesinde harita entegrasyonu ile en optimize rotalardan gidin. Sıfır evrak, maksimum verimlilik.",
        "Ürün fabrikanıza geldiğinde süreç yine tam kontrol altındadır. Workshop App ile barkod sisteminden kalite kontrole kadar her şey anlık takipte.",
        "AYKA Transport Lojistik Ekosistemi ile işini değil, şirketinin büyümesini yönet. Şimdi keşfedin."
    ]

    images = [
        r"C:\Users\PC\.gemini\antigravity\brain\2ccf657d-d981-4e7d-8e83-a72f06ed85b7\dashboard_saas_1775399630896.png",
        r"C:\Users\PC\.gemini\antigravity\brain\2ccf657d-d981-4e7d-8e83-a72f06ed85b7\dashboard_saas_1775399630896.png",  # re-use for AI part
        r"C:\Users\PC\.gemini\antigravity\brain\2ccf657d-d981-4e7d-8e83-a72f06ed85b7\driver_app_1775399834997.png",
        r"C:\Users\PC\.gemini\antigravity\brain\2ccf657d-d981-4e7d-8e83-a72f06ed85b7\workshop_ai_1775400428489.png",
        r"C:\Users\PC\.gemini\antigravity\brain\2ccf657d-d981-4e7d-8e83-a72f06ed85b7\dashboard_saas_1775399630896.png"   # re-use for outro
    ]

    clips = []
    
    for i, (text, img_path) in enumerate(zip(texts, images)):
        audio_file = f"audio_{i}.mp3"
        generate_audio(text, audio_file)
        
        # Load audio to get duration
        audio_clip = AudioFileClip(audio_file)
        duration = audio_clip.duration + 0.5  # Add 0.5 seconds pause after each sentence
        
        # Create image video clip
        img_clip = ImageClip(img_path)
        img_clip = img_clip.resize(height=1024, width=1024)
        img_clip = img_clip.set_duration(duration)
        img_clip = img_clip.set_audio(audio_clip)
        
        clips.append(img_clip)
    
    # Concatenate all clips
    print("Concatenating video clips...")
    final_video = concatenate_videoclips(clips, method="compose")
    
    # Export
    output_path = "AYKA_Transport_Reklam_Filmi.mp4"
    print(f"Exporting video to {output_path}...")
    final_video.write_videofile(
        output_path, 
        fps=24, 
        codec="libx264", 
        audio_codec="aac"
    )
    
    print(f"Done! Video successfully created at {os.path.abspath(output_path)}")
    
    # Cleanup trailing audios
    for i in range(len(texts)):
        if os.path.exists(f"audio_{i}.mp3"):
            os.remove(f"audio_{i}.mp3")

if __name__ == "__main__":
    create_video()
