import tkinter as tk
from omnihand_2025 import AgibotHandO10, EHandType
import time
import threading  # 用线程实现“GUI界面 + 后台监控”并行


class OmniHandGUI:
    def __init__(self):
        # ===================== 初始化机械手（仅初始化一次！）=====================
        self.cfg_path = "/home/agiuser/Omnihand-2025-SDK-0.8.0/python/example/conf/hardware_conf.yaml"
        self.hand_type = EHandType.RIGHT  # 明确指定右手
        try:
            self.hand = AgibotHandO10.create_hand(cfg_path=self.cfg_path, hand_type=self.hand_type)
            print("[INFO] 右手机械手初始化成功")
        except Exception as e:
            print(f"[ERROR] 机械手初始化失败: {e}")
            exit(1)
        
        # ===================== 关节名称映射（右手）=====================
        self.joint_names = [
            "R_thumb_roll_joint",    # 1 右手大拇指自旋
            "R_thumb_abad_joint",    # 2 右手大拇指侧摆
            "R_thumb_mcp_joint",     # 3 右手大拇指弯曲
            "R_index_abad_joint",    # 4 右手食指侧摆
            "R_index_pip_joint",     # 5 右手食指弯曲
            "R_middle_pip_joint",    # 6 右手中指弯曲
            "R_ring_abad_joint",     # 7 右手无名指侧摆
            "R_ring_pip_joint",      # 8 右手无名指弯曲
            "R_pinky_abad_joint",    # 9 右手小拇指侧摆
            "R_pinky_pip_joint"      # 10 右手小拇指弯曲
        ]
        
        # ===================== 启动GUI + 后台监控线程 =====================
        self.setup_ui()
        self.init_hand()
        # 启动后台监控线程（不阻塞GUI主线程）
        self.monitor_thread = threading.Thread(target=self.joint_monitor, daemon=True)
        self.monitor_thread.start()
        
    def setup_ui(self):
        # 主窗口 - 极简风格
        self.root = tk.Tk()
        self.root.title("OmniHand 2025 - 关节控制+实时监控")
        self.root.geometry("900x700")  # 扩大窗口容纳监控信息
        self.root.configure(bg='#000000')
        
        # 主框架（分左右两栏：左=控制区，右=监控区）
        main_frame = tk.Frame(self.root, bg='#000000', relief='flat', bd=0)
        main_frame.pack(fill='both', expand=True, padx=12, pady=12)
        
        # 左栏：控制区
        control_frame = tk.Frame(main_frame, bg='#0d0d0d', width=400)
        control_frame.pack(side='left', fill='both', expand=True, padx=(0, 10))
        self.setup_control_panel(control_frame)
        
        # 右栏：监控区
        monitor_frame = tk.Frame(main_frame, bg='#0d0d0d', width=400)
        monitor_frame.pack(side='right', fill='both', expand=True)
        self.setup_monitor_panel(monitor_frame)
        
    def setup_control_panel(self, parent):
        # 控制面板（原逻辑保留）
        tech_line = tk.Frame(parent, bg='#00d4ff', height=1)
        tech_line.pack(fill='x', padx=0, pady=(0, 0))
        
        title_frame = tk.Frame(parent, bg='#0d0d0d', height=40)
        title_frame.pack(fill='x', padx=20, pady=(0, 8))
        tk.Label(title_frame, text="关节位置控制", 
                bg='#0d0d0d', fg='#00d4ff', 
                font=('Consolas', 13, 'bold')).pack(anchor='w')
        
        self.setup_sliders(parent)
        
    def setup_sliders(self, parent):
        # 滑动条面板（原逻辑保留）
        sliders_frame = tk.Frame(parent, bg='#0d0d0d')
        sliders_frame.pack(fill='both', expand=True, padx=20)
        
        initial_values = [1990, 201, 3998, 409, 4097, 4096, 2048, 4096, 2038, 4100]
        self.position_sliders = []
        for i in range(10):
            joint_frame = tk.Frame(sliders_frame, bg='#151515', relief='flat', bd=0)
            joint_frame.pack(fill='x', pady=2)
            
            info_frame = tk.Frame(joint_frame, bg='#151515')
            info_frame.pack(fill='x', padx=12, pady=5)
            
            joint_label = tk.Label(info_frame, text=f"J{i+1:02d}", 
                                 bg='#151515', fg='#cccccc', 
                                 font=('Consolas', 9, 'bold'), width=4)
            joint_label.pack(side='left')
            
            slider = tk.Scale(info_frame, from_=0, to=4100, orient='horizontal',
                            bg='#151515', fg='#888888', 
                            troughcolor='#2a2a2a', activebackground='#00d4ff',
                            highlightthickness=0, bd=0, length=170, showvalue=0,
                            command=lambda v, idx=i: self.on_position_slider_change(idx, v))
            slider.set(initial_values[i])
            slider.pack(side='left', padx=(10, 15))
            
            value_label = tk.Label(info_frame, text=str(initial_values[i]), 
                                 bg='#151515', fg='#00d4ff', 
                                 font=('Consolas', 9, 'bold'), width=4)
            value_label.pack(side='right')
            
            self.position_sliders.append((slider, value_label))
            
    def setup_monitor_panel(self, parent):
        # 监控面板（新增：显示实时关节角度）
        tech_line = tk.Frame(parent, bg='#00d4ff', height=1)
        tech_line.pack(fill='x', padx=0, pady=(0, 0))
        
        title_frame = tk.Frame(parent, bg='#0d0d0d', height=40)
        title_frame.pack(fill='x', padx=20, pady=(0, 8))
        tk.Label(title_frame, text="关节角度实时监控", 
                bg='#0d0d0d', fg='#00d4ff', 
                font=('Consolas', 13, 'bold')).pack(anchor='w')
        
        # 监控信息显示区（用Text控件滚动显示）
        self.monitor_text = tk.Text(parent, bg='#151515', fg='#cccccc',
                                  font=('Consolas', 9), wrap='word',
                                  highlightthickness=0, bd=0)
        self.monitor_text.pack(fill='both', expand=True, padx=20, pady=5)
        # 设置初始提示
        self.monitor_text.insert('end', "[INFO] 监控已启动，每0.5秒更新...\n")
        self.monitor_text.config(state='disabled')  # 设为只读
        
    def init_hand(self):
        # 初始化机械手（原逻辑保留）
        try:
            init_positions = [1990, 201, 3998, 409, 4097, 4096, 2048, 4096, 2038, 4100]
            for i in range(10):
                self.hand.set_joint_position(i + 1, init_positions[i])
            self.update_slider_display(init_positions)
        except Exception as e:
            print(f"初始化失败: {e}")
            
    def on_position_slider_change(self, joint_idx, value):
        # 滑动条变化回调（原逻辑保留）
        self.position_sliders[joint_idx][1].config(text=str(int(float(value))))
        try:
            self.hand.set_joint_position(joint_idx + 1, int(float(value)))
        except Exception as e:
            print(f"关节位置设置失败: {e}")
            
    def update_slider_display(self, positions):
        # 更新滑动条显示（原逻辑保留）
        for i, (slider, label) in enumerate(self.position_sliders):
            if i < len(positions):
                slider.set(positions[i])
                label.config(text=str(positions[i]))
                
    def joint_monitor(self):
        """后台监控线程：每0.5秒读取关节角度并显示到监控面板"""
        while True:
            try:
                # 1. 读取原始弧度列表
                raw_joint_angles = self.hand.get_all_active_joint_angles()
                
                # 2. 格式化监控信息
                monitor_info = f"\n{'='*60}\n[右手实时角度] {time.strftime('%Y-%m-%d %H:%M:%S')}\n{'='*60}\n"
                monitor_info += f"原始弧度列表：\n{raw_joint_angles}\n{'-'*60}\n"
                for idx, (name, raw_angle) in enumerate(zip(self.joint_names, raw_joint_angles)):
                    angle_deg = raw_angle * 180 / 3.1415926535
                    monitor_info += f"关节{idx+1:2d} | {name:25s} | 弧度：{raw_angle} | 角度：{angle_deg:.3f}°\n"
                
                # 3. 更新监控面板（需切换到GUI主线程更新）
                self.monitor_text.config(state='normal')
                self.monitor_text.insert('end', monitor_info)
                self.monitor_text.see('end')  # 自动滚动到最新内容
                self.monitor_text.config(state='disabled')
                
            except Exception as e:
                error_info = f"\n[ERROR] 读取关节角度失败：{e}\n"
                self.monitor_text.config(state='normal')
                self.monitor_text.insert('end', error_info)
                self.monitor_text.see('end')
                self.monitor_text.config(state='disabled')
            
            # 4. 延时0.5秒
            time.sleep(0.5)
        
    def run(self):
        self.root.mainloop()


def main():
    gui = OmniHandGUI()
    gui.run()


if __name__ == '__main__':
    main()

